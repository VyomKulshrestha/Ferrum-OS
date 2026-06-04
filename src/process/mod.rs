// ============================================================================
// FerrumOS - Per-Process Address Space
// ============================================================================
// Phase 1.3 of the v0.2 completion roadmap.
//
// Provides `AddressSpace`, a per-process P4 page table that:
//   - shares the kernel's upper-half mappings (indices 256..512) so the
//     kernel code, data, heap, and physical-memory alias remain visible
//     in every user process;
//   - owns its own lower-half (indices 0..256) into which future
//     Phase 1.4 code will map the user's `PT_LOAD` segments, stack,
//     and vDSO pages.
//
// The actual `iretq`/CR3 switch that activates an address space lands
// in Phase 1.4. For now the type is constructible, mappable, and
// droppable in isolation; the kernel never activates one.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use spin::Mutex;
use x86_64::{
    align_up,
    structures::paging::{
        mapper::{Mapper, MapToError, UnmapError},
        FrameAllocator, OffsetPageTable, Page, PageSize, PageTable, PageTableFlags, PhysFrame,
        Size4KiB,
    },
    PhysAddr, VirtAddr,
};

/// First P4 index that belongs to the kernel half. Indices below this
/// are user space. The bootloader maps the kernel at 0xffff_8000_0000_0000
/// (entry 511) and the physical memory alias at 0xffff_8888_0000_0000, so
/// the kernel half always starts well above the user half.
pub const KERNEL_P4_START: usize = 256;

/// Size of a user-half mapping in bytes (lower-half P4 coverage).
pub const USER_HALF_SIZE: u64 = 1u64 << 39; // 512 GiB

// ============================================================================
// Per-process address space
// ============================================================================

/// A self-contained per-process P4 page table.
///
/// The struct holds the physical frame of the L4 table and bookkeeping
/// for every frame the kernel allocated on behalf of the user. When the
/// `AddressSpace` is dropped, every user-half frame (and the L4 frame
/// itself) is returned to the global frame allocator.
pub struct AddressSpace {
    l4_frame: PhysFrame,
    /// Frames the kernel allocated on behalf of the user while mapping
    /// their pages. We track them so `Drop` can release them.
    user_frames: Vec<PhysFrame>,
    /// Pages the user has mapped (vaddr -> length). Used to answer shell
    /// introspection and to make `Drop` idempotent.
    user_mappings: Vec<(VirtAddr, u64)>,
}

/// User-process handle. Owns its `AddressSpace` and a process id.
pub struct Process {
    pid: u64,
    name: String,
    space: Option<AddressSpace>,
}

impl Process {
    pub fn pid(&self) -> u64 {
        self.pid
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn address_space(&self) -> Option<&AddressSpace> {
        self.space.as_ref()
    }

    pub fn address_space_mut(&mut self) -> Option<&mut AddressSpace> {
        self.space.as_mut()
    }

    /// Map a user range and copy `bytes` into it.
    pub fn map_user(
        &mut self,
        vaddr: VirtAddr,
        bytes: &[u8],
        flags: PageTableFlags,
    ) -> Result<u64, MapToError<Size4KiB>> {
        let space = self.space.as_mut().ok_or(MapToError::ParentEntryHugePage)?;
        space.map_user_range(vaddr, bytes, flags)
    }

    pub fn user_frame_count(&self) -> usize {
        self.space.as_ref().map(|s| s.user_frame_count()).unwrap_or(0)
    }
}

impl AddressSpace {
    /// Allocate a fresh L4 frame and seed it with the kernel's upper-half
    /// entries. The lower half is zeroed, so user-mode code can fault
    /// without seeing the kernel.
    pub fn new() -> Result<Self, &'static str> {
        let l4_frame = crate::memory::allocate_frame().ok_or("frame allocator empty")?;
        let table = unsafe { &mut *l4_to_mut_ptr(l4_frame) };
        table.zero();

        // Copy the kernel half from the active P4 so the kernel remains
        // reachable. If the kernel later wants per-process kernel-half
        // variance (e.g. KPTI), this is the only place to change.
        let kernel_l4_phys = crate::memory::active_p4_phys();
        let kernel_l4_ptr = crate::memory::phys_to_virt(kernel_l4_phys).as_ptr::<PageTable>();
        // Safety: the kernel's L4 is mapped at phys_to_virt(active_p4_phys()).
        let kernel_l4 = unsafe { &*kernel_l4_ptr };
        for index in KERNEL_P4_START..512 {
            table[index] = kernel_l4[index].clone();
        }

        Ok(Self {
            l4_frame,
            user_frames: Vec::new(),
            user_mappings: Vec::new(),
        })
    }

    /// Physical frame of the L4 table. Phase 1.4 will load this into CR3
    /// when the process is scheduled.
    pub fn l4_frame(&self) -> PhysFrame {
        self.l4_frame
    }

    /// Number of user frames the kernel has allocated on behalf of this
    /// process (excluding the L4 itself). Useful for the shell and for
    /// diagnostics in `cmd_process`.
    pub fn user_frame_count(&self) -> usize {
        self.user_frames.len()
    }

    /// Map a contiguous user range `[vaddr, vaddr + len)` with the given
    /// flags, copying `bytes` into the freshly-allocated physical pages.
    ///
    /// `vaddr` must be page-aligned and `len` is rounded up to the next
    /// page. Returns the number of bytes actually mapped.
    pub fn map_user_range(
        &mut self,
        vaddr: VirtAddr,
        bytes: &[u8],
        flags: PageTableFlags,
    ) -> Result<u64, MapToError<Size4KiB>> {
        if vaddr.as_u64() >= USER_HALF_SIZE {
            return Err(MapToError::ParentEntryHugePage);
        }

        let len_aligned = align_up(bytes.len() as u64, Size4KiB::SIZE);
        let start_page = Page::containing_address(vaddr);
        // `len_aligned == 0` would mean zero bytes, but the chunk loop
        // also handles that. We use an exclusive end so we don't
        // accidentally map one extra page past the payload.
        let end_page_exclusive = if len_aligned == 0 {
            start_page
        } else {
            Page::containing_address(vaddr + len_aligned - 1u64) + 1
        };

        // Borrow the L4 mutably through the kernel's phys->virt alias
        // for the duration of the mapping.
        let l4_virt = crate::memory::phys_to_virt(self.l4_frame.start_address());
        let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
        let mut mapper = unsafe { OffsetPageTable::new(l4_table, crate::memory::phys_to_virt(PhysAddr::new(0))) };

        let mut allocator = GlobalFrameSource::new();

        for (offset, page) in Page::range_inclusive(start_page, end_page_exclusive - 1).enumerate() {
            let frame = allocator
                .allocate_frame()
                .ok_or(MapToError::FrameAllocationFailed)?;
            unsafe {
                mapper
                    .map_to(page, frame, flags, &mut allocator)?
                    .flush();
            }

            // Zero the page, then copy as many bytes as fit.
            let page_virt = crate::memory::phys_to_virt(frame.start_address());
            unsafe {
                core::ptr::write_bytes(page_virt.as_mut_ptr::<u8>(), 0u8, Size4KiB::SIZE as usize);
                let page_offset = offset * Size4KiB::SIZE as usize;
                let copy_len = core::cmp::min(Size4KiB::SIZE as usize, bytes.len().saturating_sub(page_offset));
                if copy_len > 0 {
                    core::ptr::copy_nonoverlapping(
                        bytes.as_ptr().add(page_offset),
                        page_virt.as_mut_ptr::<u8>(),
                        copy_len,
                    );
                }
            }

            self.user_frames.push(frame);
        }

        self.user_mappings.push((vaddr, len_aligned));
        Ok(len_aligned)
    }

    /// Unmap a previously-mapped user range and return its frames to the
    /// global allocator.
    pub fn unmap_user_range(
        &mut self,
        vaddr: VirtAddr,
        len: u64,
    ) -> Result<(), UnmapError> {
        let len_aligned = align_up(len, Size4KiB::SIZE);
        let start_page = Page::containing_address(vaddr);
        let end_page_exclusive = if len_aligned == 0 {
            start_page
        } else {
            Page::containing_address(vaddr + len_aligned - 1u64) + 1
        };

        let l4_virt = crate::memory::phys_to_virt(self.l4_frame.start_address());
        let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
        let mut mapper = unsafe { OffsetPageTable::new(l4_table, crate::memory::phys_to_virt(PhysAddr::new(0))) };

        for page in Page::range_inclusive(start_page, end_page_exclusive - 1) {
            let (frame, flush) = mapper.unmap(page)?;
            flush.flush();
            self.user_frames.retain(|f| f != &frame);
        }

        self.user_mappings.retain(|(base, size)| {
            *base != vaddr || *size != len_aligned
        });
        Ok(())
    }
}

impl Drop for AddressSpace {
    fn drop(&mut self) {
        // Free every user frame. The L4 frame itself is freed last so a
        // partial-failure unwind is still recoverable.
        let user_frames = core::mem::take(&mut self.user_frames);
        for frame in user_frames {
            crate::memory::deallocate_frame(frame);
        }
        crate::memory::deallocate_frame(self.l4_frame);
    }
}

// ============================================================================
// Frame source wrapper
// ============================================================================

struct GlobalFrameSource;

impl GlobalFrameSource {
    fn new() -> Self {
        Self
    }
}

unsafe impl FrameAllocator<Size4KiB> for GlobalFrameSource {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        crate::memory::allocate_frame()
    }
}

// ============================================================================
// Helpers
// ============================================================================

fn l4_to_mut_ptr(frame: PhysFrame) -> *mut PageTable {
    crate::memory::phys_to_virt(frame.start_address()).as_mut_ptr()
}

// ============================================================================
// Process registry
// ============================================================================

struct ProcessRecord {
    process: Process,
}

static PROCESSES: Mutex<Vec<ProcessRecord>> = Mutex::new(Vec::new());
static NEXT_PID: Mutex<u64> = Mutex::new(1);

/// Create a process record with a freshly-allocated address space.
pub fn create(name: &str) -> Result<Process, &'static str> {
    let space = AddressSpace::new()?;
    let mut next = NEXT_PID.lock();
    let pid = *next;
    *next += 1;
    let process = Process {
        pid,
        name: alloc::string::String::from(name),
        space: Some(space),
    };
    Ok(process)
}

/// Register a freshly-built process in the global table so the shell can
/// introspect it and Phase 1.4 can schedule it.
pub fn register(process: Process) -> u64 {
    let pid = process.pid;
    PROCESSES.lock().push(ProcessRecord { process });
    pid
}

/// Drop a process by pid and free its address space.
pub fn drop_by_pid(pid: u64) -> bool {
    let mut procs = PROCESSES.lock();
    let Some(index) = procs.iter().position(|r| r.process.pid == pid) else {
        return false;
    };
    procs.remove(index);
    true
}

/// List all registered process records. Each entry is a tuple of (pid,
/// name, user frame count).
pub fn list() -> Vec<(u64, String, usize)> {
    PROCESSES
        .lock()
        .iter()
        .map(|record| {
            let frames = record.process.user_frame_count();
            (record.process.pid, record.process.name.clone(), frames)
        })
        .collect()
}
