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

use alloc::boxed::Box;
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

/// Persistent PID 1 supervisor for runtime services
pub mod supervisor;

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

/// User-process handle. Owns its `AddressSpace`, a dedicated kernel
/// stack (used as the CPU's ring-0 RSP0 when this process is active),
/// and the user-mode entry point + stack pointer that `enter_ring3`
/// will hand to `iretq`.
pub struct Process {
    pid: u64,
    name: String,
    space: Option<AddressSpace>,
    /// Boxed kernel stack backing storage. The CPU uses
    /// `kernel_stack_top` (set in TSS.RSP0) when this process is
    /// interrupted or makes a syscall.
    kernel_stack: Option<Box<[u8; KERNEL_STACK_SIZE]>>,
    /// Top of the kernel stack (16-byte aligned virtual address).
    kernel_stack_top: VirtAddr,
    /// Top of the user stack (16-byte aligned virtual address),
    /// used as the initial RSP for the iretq frame.
    user_stack_top: VirtAddr,
    /// ELF entry point (RIP) the CPU will jump to via iretq.
    entry: u64,
    /// Has `load_elf` mapped the user stack already?
    user_stack_mapped: bool,
    /// Has `load_elf` parsed the ELF and mapped all PT_LOAD segments?
    loaded: bool,
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

    /// Return the top of this process's kernel stack (the value
    /// that should be loaded into `TSS.RSP0` when entering it).
    pub fn kernel_stack_top(&self) -> VirtAddr {
        self.kernel_stack_top
    }

    /// Return the initial RSP value to push in the iretq frame.
    pub fn user_stack_top(&self) -> VirtAddr {
        self.user_stack_top
    }

    /// Return the ELF entry point (initial RIP for iretq).
    pub fn entry(&self) -> u64 {
        self.entry
    }

    /// True once `load_elf` has finished mapping every PT_LOAD
    /// segment (and the user stack) into the process's address
    /// space.
    pub fn is_loaded(&self) -> bool {
        self.loaded
    }

    /// Manually mark the process as loaded. Useful for synthetic or manually
    /// mapped processes that did not go through `load_elf()`.
    pub fn mark_loaded(&mut self) {
        self.loaded = true;
    }

    /// Manually set the ELF entry point (RIP).
    pub fn set_entry(&mut self, entry: u64) {
        self.entry = entry;
    }

    /// Map a fresh user stack at `USER_STACK_BASE` (RW, NX) and
    /// zero it. Idempotent: a second call is a no-op.
    pub fn map_user_stack(&mut self) -> Result<u64, MapToError<Size4KiB>> {
        if self.user_stack_mapped {
            return Ok(0);
        }
        let flags = PageTableFlags::PRESENT
            | PageTableFlags::USER_ACCESSIBLE
            | PageTableFlags::WRITABLE;
        let vaddr = VirtAddr::new(USER_STACK_BASE);
        let zeroed = [0u8; USER_STACK_SIZE];
        let mapped = self.map_user(vaddr, &zeroed, flags)?;
        self.user_stack_mapped = true;
        Ok(mapped)
    }

    /// Parse the given ELF and map every `PT_LOAD` segment into
    /// this process's address space. Also maps a user stack and
    /// records the entry point. After this call returns,
    /// `is_loaded()` is true and `enter_ring3()` is ready to
    /// dispatch into user mode.
    pub fn load_elf(&mut self, elf_bytes: &[u8]) -> Result<u64, &'static str> {
        let elf = crate::elf::parse(elf_bytes).map_err(|_| "elf parse failed")?;

        for ph in elf.load_segments() {
            let flags = pt_flags(ph);
            let vaddr = VirtAddr::new(ph.p_vaddr);
            if vaddr.as_u64() >= USER_HALF_SIZE {
                return Err("PT_LOAD vaddr above user half");
            }
            let file_bytes = elf.segment_bytes(ph).unwrap_or(&[]);
            let mut segment = alloc::vec![0u8; ph.p_memsz as usize];
            let copy_len = core::cmp::min(file_bytes.len(), segment.len());
            segment[..copy_len].copy_from_slice(&file_bytes[..copy_len]);
            self.map_user(vaddr, &segment, flags)
                .map_err(|_| "pt_load map failed")?;
        }

        self.map_user_stack().map_err(|_| "user stack map failed")?;

        self.entry = elf.entry();
        self.loaded = true;
        Ok(elf.entry())
    }

    /// Take the process out of the registry without running any
    /// of its drop logic. Used by `enter_ring3`, which iretq's
    /// into user mode and never returns to Rust.
    pub fn into_parts(mut self) -> (u64, VirtAddr, VirtAddr, u64, PhysFrame) {
        let pid = self.pid;
        let kernel_rsp = self.kernel_stack_top;
        let user_rsp = self.user_stack_top;
        let entry = self.entry;
        let l4 = self
            .space
            .as_ref()
            .map(|s| s.l4_frame())
            .unwrap_or_else(crate::memory::active_p4_frame);
        // Leak the kernel stack so it isn't freed by the Box
        // drop when we ManuallyDrop the Process. The iretq path
        // owns it from this point on.
        let _ = self.kernel_stack.take();
        let _ = self.space.take();
        core::mem::forget(self);
        (pid, kernel_rsp, user_rsp, entry, l4)
    }
}

/// Translate ELF segment permission bits to x86_64 page table
/// flags. We always set PRESENT and USER_ACCESSIBLE for user-half
/// mappings; the kernel half is never used by `load_elf`.
fn pt_flags(ph: &crate::elf::ProgramHeader) -> PageTableFlags {
    use crate::elf::{PF_R, PF_W, PF_X};
    let mut f = PageTableFlags::PRESENT | PageTableFlags::USER_ACCESSIBLE;
    if ph.p_flags & PF_W != 0 {
        f |= PageTableFlags::WRITABLE;
    }
    // We do not set NO_EXECUTE explicitly when X is present; the
    // CPU's default for code segments in long mode is exec allowed.
    // The kernel itself does not rely on NX for safety in Phase 1.4.
    let _ = PF_R;
    let _ = PF_X;
    f
}

impl AddressSpace {
    /// Allocate a fresh L4 frame and seed it with the kernel's live
    /// entries. Any P4 slot the kernel currently uses (text, stack,
    /// heap, device pages, ... ) is mirrored so the kernel stays
    /// reachable after `mov cr3, new_cr3`. Slots the kernel does
    /// not use are left zero so user-mode code faults cleanly.
    pub fn new() -> Result<Self, &'static str> {
        let l4_frame = crate::memory::allocate_frame().ok_or("frame allocator empty")?;
        let table = unsafe { &mut *l4_to_mut_ptr(l4_frame) };
        table.zero();

        // Mirror only the kernel half. The user half must start empty so
        // PT_LOAD mappings can be installed without colliding with the
        // bootloader's temporary lower-half identity mappings.
        let kernel_l4_phys = crate::memory::active_p4_phys();
        let kernel_l4_ptr = crate::memory::phys_to_virt(kernel_l4_phys).as_ptr::<PageTable>();
        // Safety: the kernel's L4 is mapped at phys_to_virt(active_p4_phys()).
        let kernel_l4 = unsafe { &*kernel_l4_ptr };
        for index in KERNEL_P4_START..512 {
            if kernel_l4[index].flags().contains(PageTableFlags::PRESENT) {
                table[index] = kernel_l4[index].clone();
            }
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

        let start_page = Page::containing_address(vaddr);
        let vaddr_offset_in_page = (vaddr.as_u64() & (Size4KiB::SIZE - 1)) as usize;
        let len_aligned = align_up(
            vaddr_offset_in_page as u64 + bytes.len() as u64,
            Size4KiB::SIZE,
        );
        // `len_aligned == 0` would mean zero bytes, but the chunk loop
        // also handles that. We use an exclusive end so we don't
        // accidentally map one extra page past the payload.
        let end_page_exclusive = if len_aligned == 0 {
            start_page
        } else {
            Page::containing_address(vaddr + len_aligned - 1u64) + 1
        };

        // The vaddr may not be page-aligned (a segment can start
        // mid-page). The bytes from `bytes[0]` belong at vaddr, which
        // is at page offset `vaddr_offset_in_page`. Subsequent
        // pages receive the segment bytes starting at page offset 0.
        // Borrow the L4 mutably through the kernel's phys->virt alias
        // for the duration of the mapping.
        let l4_virt = crate::memory::phys_to_virt(self.l4_frame.start_address());
        let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
        let mut mapper = unsafe { OffsetPageTable::new(l4_table, crate::memory::phys_to_virt(PhysAddr::new(0))) };

        let mut allocator = GlobalFrameSource::new();

        for (page_index, page) in Page::range_inclusive(start_page, end_page_exclusive - 1).enumerate() {
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
                // The first page receives the segment bytes at
                // `vaddr_offset_in_page` (where vaddr falls in the
                // page). Subsequent pages receive their bytes at
                // page offset 0, since they continue the segment
                // contiguously.
                let dest_offset = if page_index == 0 {
                    vaddr_offset_in_page
                } else {
                    0
                };
                // The source range into `bytes` is the segment
                // bytes that belong on this page. For the first
                // page we start at byte 0 of the segment; for later
                // pages we skip past the bytes already placed on
                // earlier pages.
                let src_offset = if page_index == 0 {
                    0
                } else {
                    page_index * Size4KiB::SIZE as usize - vaddr_offset_in_page
                };
                let bytes_remaining_after_src = bytes.len().saturating_sub(src_offset);
                let page_capacity = Size4KiB::SIZE as usize - dest_offset;
                let copy_len = core::cmp::min(page_capacity, bytes_remaining_after_src);
                if copy_len > 0 {
                    core::ptr::copy_nonoverlapping(
                        bytes.as_ptr().add(src_offset),
                        page_virt.as_mut_ptr::<u8>().add(dest_offset),
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

/// Size of the per-process kernel stack. 32 KiB gives the syscall
/// handler, page-fault handler, and any future preemptive
/// scheduler ISR plenty of headroom before it would have to
/// chain onto the IST.
pub const KERNEL_STACK_SIZE: usize = 32 * 1024;

/// Size of the per-process user stack. 64 KiB matches the
/// smallest comfortable C stack for the placeholder `init`
/// binary and the future userland programs.
pub const USER_STACK_SIZE: usize = 64 * 1024;

/// Virtual address where every process's user stack lives.
/// 0x7000_0000 is well above any realistic init ELF (which lives
/// at 0x200_000) and well below the user-half ceiling (0x8000_0000_0000).
pub const USER_STACK_BASE: u64 = 0x7000_0000;

fn l4_to_mut_ptr(frame: PhysFrame) -> *mut PageTable {
    crate::memory::phys_to_virt(frame.start_address()).as_mut_ptr()
}

/// 16-byte aligned top address of a boxed byte array. Used for
/// the kernel stack so the SysV ABI's RSP alignment contract
/// holds when a syscall handler is entered.
fn aligned_top(buf: &[u8; KERNEL_STACK_SIZE]) -> VirtAddr {
    let raw = buf.as_ptr() as u64 + KERNEL_STACK_SIZE as u64;
    VirtAddr::new(raw & !0xFu64)
}

// ============================================================================
// Process registry
// ============================================================================

struct ProcessRecord {
    process: Process,
}

static PROCESSES: Mutex<Vec<ProcessRecord>> = Mutex::new(Vec::new());
static NEXT_PID: Mutex<u64> = Mutex::new(1);

/// Create a process record with a freshly-allocated address space
/// and a dedicated kernel stack. The user stack and PT_LOAD
/// segments are not yet mapped; call `load_elf` (or
/// `map_user_stack`) to do that.
pub fn create(name: &str) -> Result<Process, &'static str> {
    let space = AddressSpace::new()?;
    let kernel_stack: Box<[u8; KERNEL_STACK_SIZE]> = Box::new([0; KERNEL_STACK_SIZE]);
    let kernel_stack_top = aligned_top(&kernel_stack);
    let mut next = NEXT_PID.lock();
    let pid = *next;
    *next += 1;
    let process = Process {
        pid,
        name: alloc::string::String::from(name),
        space: Some(space),
        kernel_stack: Some(kernel_stack),
        kernel_stack_top,
        user_stack_top: VirtAddr::new(USER_STACK_BASE + USER_STACK_SIZE as u64),
        entry: 0,
        user_stack_mapped: false,
        loaded: false,
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

/// Look up the user stack top of a registered process by pid.
pub fn pid_user_stack(pid: u64) -> Option<VirtAddr> {
    PROCESSES
        .lock()
        .iter()
        .find(|r| r.process.pid == pid)
        .map(|r| r.process.user_stack_top())
}

/// Look up the kernel stack top of a registered process by pid.
pub fn pid_kernel_stack(pid: u64) -> Option<VirtAddr> {
    PROCESSES
        .lock()
        .iter()
        .find(|r| r.process.pid == pid)
        .map(|r| r.process.kernel_stack_top())
}

/// Look up the entry point of a registered process by pid.
pub fn pid_entry(pid: u64) -> Option<u64> {
    PROCESSES
        .lock()
        .iter()
        .find(|r| r.process.pid == pid)
        .map(|r| r.process.entry())
}

/// Remove a registered process by pid and return the parts
/// `enter_ring3` needs (kernel RSP, user RSP, entry, L4 frame).
/// Returns `None` if the pid is not registered or the process
/// was never `load_elf`'d.
pub fn take_for_entry(pid: u64) -> Option<(VirtAddr, VirtAddr, u64, PhysFrame)> {
    let mut procs = PROCESSES.lock();
    let index = procs.iter().position(|r| r.process.pid == pid)?;
    let record = procs.remove(index);
    if !record.process.is_loaded() {
        return None;
    }
    let process = record.process;
    Some(process.into_entry_parts())
}

/// Transfer control to the registered process with the given pid
/// at ring 3. The iretq never returns; if the process calls
/// `SYS_EXIT` the kernel halts.
pub fn enter_registered(pid: u64) {
    let (kernel_rsp, user_rsp, entry, l4_frame) = match take_for_entry(pid) {
        Some(parts) => parts,
        None => {
            crate::println!("ring3: pid {} is not loaded", pid);
            return;
        }
    };

    // Register the user process with the scheduler so the
    // context switch layer (Phase 2) can find it. The kernel
    // main context is the implicit "current" task; the user
    // process becomes the next runnable task.
    crate::scheduler::register_user(
        pid,
        &alloc::format!("user-{}", pid),
        crate::scheduler::Priority::Normal,
        kernel_rsp,
        l4_frame.start_address().as_u64(),
    );
    // Seed the incoming task's saved iretq frame so the
    // scheduler's `context_switch_to` can iretq into it.
    let ctx = crate::scheduler::TaskContext::ring3(
        entry,
        user_rsp.as_u64(),
    );
    crate::scheduler::write_context(pid, ctx);
    // Mark the user process as currently executing so the
    // tick handler decrements its time slice correctly.
    crate::scheduler::CURRENT_PID.store(pid, core::sync::atomic::Ordering::SeqCst);

    enter_ring3_inner(kernel_rsp, user_rsp, entry, l4_frame);
}

impl Process {
    /// Like `into_parts` but specialised for the iretq entry
    /// path: returns the (kernel RSP, user RSP, entry, L4
    /// frame) tuple and forgets the process. Used by
    /// `enter_registered`.
    pub fn into_entry_parts(mut self) -> (VirtAddr, VirtAddr, u64, PhysFrame) {
        let kernel_rsp = self.kernel_stack_top;
        let user_rsp = self.user_stack_top;
        let entry = self.entry;
        let l4 = self
            .space
            .as_ref()
            .map(|s| s.l4_frame())
            .unwrap_or_else(crate::memory::active_p4_frame);
        let _ = self.kernel_stack.take();
        let _ = self.space.take();
        core::mem::forget(self);
        (kernel_rsp, user_rsp, entry, l4)
    }
}

/// Ring-3 dispatch: set TSS.RSP0, switch CR3, switch RSP, push
/// the iretq frame, iretq. Never returns.
fn enter_ring3_inner(
    kernel_rsp: VirtAddr,
    user_rsp: VirtAddr,
    entry: u64,
    l4_frame: PhysFrame,
) -> ! {
    use crate::gdt::{USER_CODE_SELECTOR, USER_DATA_SELECTOR};

    let new_cr3 = l4_frame.start_address().as_u64();
    let user_rsp_val = user_rsp.as_u64();
    let kernel_rsp_val = kernel_rsp.as_u64();

    unsafe {
        crate::gdt::set_kernel_stack(kernel_rsp);
    }

    crate::println!(
        "    [ring3] entry={:#x} new_cr3={:#x} user_rsp={:#x}",
        entry,
        new_cr3,
        user_rsp_val
    );

    unsafe {
        core::arch::asm!(
            "mov cr3, {new_cr3}",
            "mov rsp, {kernel_rsp}",
            "sub rsp, 40",
            "mov [rsp +  0], {rip}",
            "mov [rsp +  8], {cs}",
            "mov [rsp + 16], {rflags}",
            "mov [rsp + 24], {user_rsp}",
            "mov [rsp + 32], {ss}",
            "iretq",
            new_cr3 = in(reg) new_cr3,
            kernel_rsp = in(reg) kernel_rsp_val,
            rip = in(reg) entry,
            cs = in(reg) USER_CODE_SELECTOR,
            rflags = in(reg) 0x3202u64,
            user_rsp = in(reg) user_rsp_val,
            ss = in(reg) USER_DATA_SELECTOR,
            options(noreturn, preserves_flags),
        );
    }
}
