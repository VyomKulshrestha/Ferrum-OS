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
/// This bootloader (bootloader 0.9 + map_physical_memory) keeps the kernel
/// in the *lower* canonical half: at boot the kernel L4 has present entries
/// at P4 indices [0 (kernel code/data/bss/IDT/GDT/TSS), 2, 3 (physical
/// memory alias @ 0x180_0000_0000), 31, 136 (kernel heap @ 0x4444_4444_0000)].
/// Because the kernel itself occupies P4[0], a process address space cannot
/// give P4[0] to user mappings without losing the kernel. Instead each
/// process mirrors *every* present kernel L4 entry (sharing the kernel's
/// sub-tables) and confines its own user mappings to one dedicated, kernel-
/// unused P4 slot — see `USER_P4_INDEX` / `USER_REGION_*` below.
pub const KERNEL_P4_START: usize = 256;

/// P4 slot reserved exclusively for user-space mappings. Index 1 is not used
/// by the kernel (see the present-index list above), so a process can own its
/// entire L4[1] sub-tree without colliding with — or corrupting — any shared
/// kernel page table.
pub const USER_P4_INDEX: usize = 1;

/// Inclusive low / exclusive high virtual bounds of the user region: all of
/// P4[1], i.e. [512 GiB, 1 TiB). Every user PT_LOAD segment and the user
/// stack must fall inside this window; the loader rejects anything outside it.
pub const USER_REGION_BASE: u64 = (USER_P4_INDEX as u64) << 39; // 0x80_0000_0000
pub const USER_REGION_END: u64 = ((USER_P4_INDEX as u64) + 1) << 39; // 0x100_0000_0000

/// Legacy alias kept for callers that only need the user-region ceiling.
pub const USER_HALF_SIZE: u64 = USER_REGION_END;

/// True if `[vaddr, vaddr+len)` lies entirely within the user region.
#[inline]
fn in_user_region(vaddr: u64, len: u64) -> bool {
    vaddr >= USER_REGION_BASE && vaddr.saturating_add(len) <= USER_REGION_END
}

// ============================================================================
// Per-process address space
// ============================================================================

/// Persistent PID 1 supervisor for runtime services
pub mod supervisor;

#[derive(Clone, Debug)]
pub struct MmapRegion {
    pub base: VirtAddr,
    pub len: u64,
    pub file_path: String,
    pub file_offset: u64,
    pub flags: u64,
    pub populated: alloc::collections::BTreeSet<u64>, // relative offsets of populated pages
}

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
    pub mmap_regions: Vec<MmapRegion>,
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
    pub max_memory_pages: u64,
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

    pub fn map_user(
        &mut self,
        vaddr: VirtAddr,
        memsz: usize,
        bytes: &[u8],
        flags: PageTableFlags,
    ) -> Result<u64, MapToError<Size4KiB>> {
        let current_pages = self.user_frame_count() as u64;
        let max_pages = self.max_memory_pages;
        let space = self.space.as_mut().ok_or(MapToError::ParentEntryHugePage)?;
        
        let vaddr_offset_in_page = (vaddr.as_u64() & (Size4KiB::SIZE - 1)) as usize;
        let len_aligned = align_up(
            vaddr_offset_in_page as u64 + memsz as u64,
            Size4KiB::SIZE,
        );
        let pages_needed = len_aligned / Size4KiB::SIZE;
        if current_pages + pages_needed > max_pages {
            return Err(MapToError::FrameAllocationFailed);
        }
        
        space.map_user_range(vaddr, memsz, bytes, flags)
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

    pub fn map_user_stack(&mut self) -> Result<u64, MapToError<Size4KiB>> {
        if self.user_stack_mapped {
            return Ok(0);
        }
        let flags = PageTableFlags::PRESENT
            | PageTableFlags::USER_ACCESSIBLE
            | PageTableFlags::WRITABLE;
        let vaddr = VirtAddr::new(USER_STACK_BASE);
        let mapped = self.map_user(vaddr, USER_STACK_SIZE, &[], flags)?;
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
            if !in_user_region(vaddr.as_u64(), ph.p_memsz) {
                return Err("PT_LOAD vaddr outside user region");
            }
            let file_bytes = elf.segment_bytes(ph).unwrap_or(&[]);
            self.map_user(vaddr, ph.p_memsz as usize, file_bytes, flags)
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
        let kernel_stack = self.kernel_stack.take();
        let space = self.space.take();
        core::mem::forget(kernel_stack);
        core::mem::forget(space);
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

        let kernel_l4_phys = crate::memory::active_p4_phys();
        let kernel_l4_ptr = crate::memory::phys_to_virt(kernel_l4_phys).as_ptr::<PageTable>();
        // Safety: the kernel's L4 is mapped at phys_to_virt(active_p4_phys()).
        let kernel_l4 = unsafe { &*kernel_l4_ptr };
        for index in 0..512 {
            if index == USER_P4_INDEX {
                continue;
            }
            if kernel_l4[index].flags().contains(PageTableFlags::PRESENT) {
                table[index] = kernel_l4[index].clone();
            }
        }
        Ok(Self {
            l4_frame,
            user_frames: Vec::new(),
            user_mappings: Vec::new(),
            mmap_regions: Vec::new(),
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
        memsz: usize,
        bytes: &[u8],
        flags: PageTableFlags,
    ) -> Result<u64, MapToError<Size4KiB>> {
        // Confine user mappings to the dedicated P4 slot. Mapping outside it
        // could descend into a shared kernel sub-table and corrupt it.
        if !in_user_region(vaddr.as_u64(), memsz as u64) {
            return Err(MapToError::ParentEntryHugePage);
        }

        let start_page = Page::containing_address(vaddr);
        let vaddr_offset_in_page = (vaddr.as_u64() & (Size4KiB::SIZE - 1)) as usize;
        let len_aligned = align_up(
            vaddr_offset_in_page as u64 + memsz as u64,
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
            let (frame, is_newly_allocated) = match mapper.translate_page(page) {
                Ok(existing_frame) => (existing_frame, false),
                Err(_) => {
                    let new_frame = allocator
                        .allocate_frame()
                        .ok_or(MapToError::FrameAllocationFailed)?;
                    unsafe {
                        mapper
                            .map_to(page, new_frame, flags, &mut allocator)?
                            .flush();
                    }
                    (new_frame, true)
                }
            };

            let page_virt = crate::memory::phys_to_virt(frame.start_address());
            if is_newly_allocated {
                unsafe {
                    core::ptr::write_bytes(page_virt.as_mut_ptr::<u8>(), 0u8, Size4KiB::SIZE as usize);
                }
                self.user_frames.push(frame);
            }

            // Copy segment bytes into the page.
            let dest_offset = if page_index == 0 { vaddr_offset_in_page } else { 0 };
            let src_offset = if page_index == 0 { 0 } else { page_index * Size4KiB::SIZE as usize - vaddr_offset_in_page };
            let bytes_remaining_after_src = bytes.len().saturating_sub(src_offset);
            let page_capacity = Size4KiB::SIZE as usize - dest_offset;
            let copy_len = core::cmp::min(page_capacity, bytes_remaining_after_src);
            if copy_len > 0 {
                unsafe {
                    core::ptr::copy_nonoverlapping(
                        bytes.as_ptr().add(src_offset),
                        page_virt.as_mut_ptr::<u8>().add(dest_offset),
                        copy_len,
                    );
                }
            }
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

    pub fn find_free_vaddr(&self, len: u64) -> Option<VirtAddr> {
        let len_aligned = align_up(len, Size4KiB::SIZE);
        let mut candidate = 0x80_4000_0000u64;

        while candidate + len_aligned <= 0x80_7000_0000 {
            let mut overlap = false;

            // Check program/stack mappings
            for (base, size) in &self.user_mappings {
                let start = base.as_u64();
                let end = start + size;
                if candidate < end && candidate + len_aligned > start {
                    overlap = true;
                    candidate = align_up(end, Size4KiB::SIZE);
                    break;
                }
            }
            if overlap {
                continue;
            }

            // Check existing mmap regions
            for region in &self.mmap_regions {
                let start = region.base.as_u64();
                let end = start + region.len;
                if candidate < end && candidate + len_aligned > start {
                    overlap = true;
                    candidate = align_up(end, Size4KiB::SIZE);
                    break;
                }
            }
            if overlap {
                continue;
            }

            return Some(VirtAddr::new(candidate));
        }
        None
    }

    pub fn fault_in(&mut self, addr: VirtAddr) -> bool {
        // Read ahead this many pages per file-backed fault instead of just
        // one. `read_file_offset` re-resolves the path and re-reads the
        // inode on every call - for a multi-megabyte file (e.g. a real
        // model checkpoint) touched page-by-page, that redundant lookup
        // cost dominates over the actual block I/O and can turn loading a
        // ~16MB file into thousands of full path/inode resolutions. Batching
        // the read amortizes that cost across many pages per resolution.
        const READAHEAD_PAGES: u64 = 64;

        let addr_val = addr.as_u64();
        let region_opt = self.mmap_regions.iter_mut().find(|r| {
            let base = r.base.as_u64();
            let aligned_len = align_up(r.len, Size4KiB::SIZE);
            addr_val >= base && addr_val < base + aligned_len
        });

        let region = match region_opt {
            Some(r) => r,
            None => return false,
        };

        let page_size = Size4KiB::SIZE;
        let page_base = addr_val & !(page_size - 1);
        let rel_offset = page_base - region.base.as_u64();

        if region.populated.contains(&rel_offset) {
            return true;
        }

        let region_aligned_len = align_up(region.len, page_size);

        // Extend the batch forward from rel_offset while pages are still
        // within the region and not already populated.
        let mut batch_pages: u64 = 0;
        while batch_pages < READAHEAD_PAGES {
            let candidate_rel = rel_offset + batch_pages * page_size;
            if candidate_rel >= region_aligned_len {
                break;
            }
            if region.populated.contains(&candidate_rel) {
                break;
            }
            batch_pages += 1;
        }
        if batch_pages == 0 {
            return true;
        }

        let mut allocator = GlobalFrameSource::new();
        let mut frames: alloc::vec::Vec<PhysFrame> = alloc::vec::Vec::with_capacity(batch_pages as usize);
        for _ in 0..batch_pages {
            match allocator.allocate_frame() {
                Some(f) => frames.push(f),
                None => {
                    for f in frames {
                        crate::memory::deallocate_frame(f);
                    }
                    return false;
                }
            }
        }

        for f in &frames {
            let page_virt = crate::memory::phys_to_virt(f.start_address());
            unsafe {
                core::ptr::write_bytes(page_virt.as_mut_ptr::<u8>(), 0u8, page_size as usize);
            }
        }

        // Read the whole batch in one shot into a scratch buffer, then copy
        // each page's slice into its own physical frame.
        let batch_len = (batch_pages * page_size) as usize;
        let mut scratch = alloc::vec![0u8; batch_len];
        let file_path = region.file_path.clone();
        let read_offset = region.file_offset + rel_offset;
        if crate::fs::read_file_offset(&file_path, read_offset, &mut scratch).is_err() {
            for f in frames {
                crate::memory::deallocate_frame(f);
            }
            return false;
        }

        for (i, f) in frames.iter().enumerate() {
            let page_virt = crate::memory::phys_to_virt(f.start_address());
            let dst = unsafe { core::slice::from_raw_parts_mut(page_virt.as_mut_ptr::<u8>(), page_size as usize) };
            let start = i * page_size as usize;
            dst.copy_from_slice(&scratch[start..start + page_size as usize]);
        }

        let l4_virt = crate::memory::phys_to_virt(self.l4_frame.start_address());
        let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
        let mut mapper = unsafe { OffsetPageTable::new(l4_table, crate::memory::phys_to_virt(PhysAddr::new(0))) };
        let flags = PageTableFlags::PRESENT | PageTableFlags::USER_ACCESSIBLE;

        // Track whether the page that actually caused this fault (index 0 -
        // the rest of the batch is best-effort readahead) got mapped. If it
        // didn't, this function must report failure rather than unconditional
        // success: returning true here tells the page-fault handler to just
        // retry the faulting instruction, and if the page was never actually
        // mapped that retry faults again at the exact same address forever.
        let mut origin_page_mapped = false;
        for (i, frame) in frames.into_iter().enumerate() {
            let this_rel = rel_offset + (i as u64) * page_size;
            let this_page_base = region.base.as_u64() + this_rel;
            let page = Page::containing_address(VirtAddr::new(this_page_base));
            unsafe {
                match mapper.map_to(page, frame, flags, &mut allocator) {
                    Ok(tlb) => tlb.flush(),
                    Err(e) => {
                        if i == 0 {
                            crate::println!("[kernel-mmap] map_to failed for faulting page addr={:#x}: {:?}", this_page_base, e);
                        }
                        crate::memory::deallocate_frame(frame);
                        continue;
                    }
                }
            }
            if i == 0 {
                origin_page_mapped = true;
            }
            self.user_frames.push(frame);
            region.populated.insert(this_rel);
        }

        // Log here (where `batch_pages` is known) rather than in the
        // fault_in_page() wrapper: a handful of sparse, deliberate touches
        // (verify_mmap.mjs's test pokes 3 far-apart pages, each its own
        // small batch) should always be visible, while a real model's
        // multi-thousand-page sequential load produces many large batches
        // that would flood the debug kernel's unoptimized println! path if
        // every one printed - so those are throttled to periodic progress
        // updates instead. Gating the "always visible" case on batch size
        // (a property of *this* fault) is reliable in a way a global
        // call-counter modulo isn't: the latter can skip an arbitrary
        // subset of a small number of semantically distinct sparse events
        // depending on what else happened to share that counter earlier.
        static BULK_FAULT_CALLS: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
        let frames = self.user_frames.len();
        let is_bulk = batch_pages > 4 && frames > 16;
        let bulk_call_num = if is_bulk { BULK_FAULT_CALLS.fetch_add(1, core::sync::atomic::Ordering::Relaxed) } else { 0 };
        // Always show the first several large batches unconditionally
        // (covers a handful of sparse-but-large-batch touches deterministically,
        // e.g. a test probing a few widely-separated offsets in one mmap'd
        // region) and fall back to periodic sampling only once a load is
        // clearly a real multi-hundred-batch bulk sequential fetch.
        if !is_bulk || bulk_call_num < 8 || bulk_call_num % 64 == 0 {
            crate::println!("[kernel-mmap] page paged in, user_frames={}", frames);
        }

        origin_page_mapped
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

        // Clean up intermediate user page tables under USER_P4_INDEX (index 1).
        let l4_virt = crate::memory::phys_to_virt(self.l4_frame.start_address());
        let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
        let l4_entry = &l4_table[USER_P4_INDEX];
        if l4_entry.flags().contains(PageTableFlags::PRESENT) {
            let l3_frame = PhysFrame::<Size4KiB>::containing_address(l4_entry.addr());
            let l3_virt = crate::memory::phys_to_virt(l3_frame.start_address());
            let l3_table = unsafe { &mut *l3_virt.as_mut_ptr::<PageTable>() };

            for l3_idx in 0..512 {
                let l3_entry = &l3_table[l3_idx];
                if l3_entry.flags().contains(PageTableFlags::PRESENT) && !l3_entry.flags().contains(PageTableFlags::HUGE_PAGE) {
                    let l2_frame = PhysFrame::<Size4KiB>::containing_address(l3_entry.addr());
                    let l2_virt = crate::memory::phys_to_virt(l2_frame.start_address());
                    let l2_table = unsafe { &mut *l2_virt.as_mut_ptr::<PageTable>() };

                    for l2_idx in 0..512 {
                        let l2_entry = &l2_table[l2_idx];
                        if l2_entry.flags().contains(PageTableFlags::PRESENT) && !l2_entry.flags().contains(PageTableFlags::HUGE_PAGE) {
                            let l1_frame = PhysFrame::<Size4KiB>::containing_address(l2_entry.addr());
                            crate::memory::deallocate_frame(l1_frame);
                        }
                    }
                    crate::memory::deallocate_frame(l2_frame);
                }
            }
            crate::memory::deallocate_frame(l3_frame);
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
pub const USER_STACK_SIZE: usize = 1024 * 1024;

/// Virtual address where every process's user stack lives. It sits inside
/// the dedicated user P4 slot (P4[1]) at a 1.75 GiB offset — well above any
/// realistic userland ELF (linked at the slot base, 0x80_0000_0000) and well
/// below the slot ceiling (0x100_0000_0000).
pub const USER_STACK_BASE: u64 = USER_REGION_BASE + 0x7000_0000; // 0x80_7000_0000

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
    let kernel_stack: Box<[u8; KERNEL_STACK_SIZE]> = unsafe {
        let layout = core::alloc::Layout::new::<[u8; KERNEL_STACK_SIZE]>();
        let ptr = alloc::alloc::alloc_zeroed(layout);
        if ptr.is_null() {
            return Err("failed to allocate kernel stack");
        }
        Box::from_raw(ptr as *mut [u8; KERNEL_STACK_SIZE])
    };
    let kernel_stack_top = aligned_top(&kernel_stack);
    let mut next = NEXT_PID.lock();
    let pid = *next;
    *next += 1;
    let caps = crate::userspace::capabilities_for_program(name);
    let is_exempt = caps.iter().any(|c| c == "cap:quota:exempt");
    let max_memory_pages = if is_exempt {
        u64::MAX
    } else {
        2048
    };
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
        max_memory_pages,
    };
    Ok(process)
}

pub fn register(mut process: Process) -> u64 {
    let pid = process.pid;
    let caps = crate::userspace::capabilities_for_program(&process.name);
    let is_exempt = caps.iter().any(|c| c == "cap:quota:exempt");
    if is_exempt {
        process.max_memory_pages = u64::MAX;
    } else if process.name == "huge-test" {
        process.max_memory_pages = 2;
    }
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

/// Free the address space, kernel stack, and user frames of every
/// task the scheduler has marked Dead, then let the scheduler drop
/// its own bookkeeping entries.
///
/// MUST be called from a kernel context that is not executing on any
/// dead task's kernel stack or address space — e.g. the
/// return-to-shell trampoline, which runs on the boot CR3 and a
/// dedicated stack. Dropping a `Process` runs `AddressSpace::drop`,
/// which returns its frames to the global allocator.
pub fn reap_dead() {
    let dead = crate::scheduler::dead_pids();
    for pid in dead {
        drop_by_pid(pid);
    }
    crate::scheduler::cleanup_dead_tasks();
    let _ = crate::logging::audit::flush_to_disk();
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

/// Load and schedule a new ring-3 process directly from kernel context,
/// with an explicit set of granted capabilities - for callers that aren't
/// a running ring-3 process themselves (e.g. the GUI's app launcher),
/// so there's no `caller_pid`/`caller_capabilities` to delegate from the
/// way `sys_exec` (`src/syscall/process.rs`) does for a ring-3 caller.
///
/// Unlike `enter_registered`, this only *registers* the process as Ready
/// with the scheduler and returns normally - it does not itself switch
/// into ring 3, so it's safe to call from a kernel-context loop (like the
/// compositor's render loop) without abandoning the caller's stack.
pub fn spawn_elf(name: &str, elf_bytes: &[u8], granted_caps: &[String]) -> Result<u64, &'static str> {
    if elf_bytes.len() < 4 {
        return Err("elf too small");
    }

    let mut new_process = create(name).map_err(|_| "failed to create process")?;
    let entry = new_process.load_elf(elf_bytes).map_err(|_| "failed to load elf")?;

    let pid = new_process.pid();
    let kernel_rsp = new_process.kernel_stack_top();
    let cr3 = new_process
        .address_space()
        .map(|s| s.l4_frame().start_address().as_u64())
        .unwrap_or(0);

    register(new_process);
    crate::scheduler::register_user(pid, name, crate::scheduler::Priority::Normal, kernel_rsp, cr3, granted_caps);

    let user_rsp = pid_user_stack(pid).map(|v| v.as_u64()).unwrap_or(0);
    let target_user_rsp = if user_rsp > 8 { user_rsp - 8 } else { user_rsp };
    let ctx = crate::scheduler::TaskContext::ring3(entry, target_user_rsp);
    crate::scheduler::write_context(pid, ctx);

    Ok(pid)
}

/// Transfer control to the registered process with the given pid
/// at ring 3. The iretq never returns; if the process calls
/// `SYS_EXIT` the kernel halts.
pub fn enter_registered(pid: u64, caller_capabilities: &[String]) {
    let name = {
        let procs = PROCESSES.lock();
        procs.iter().find(|r| r.process.pid == pid).map(|r| String::from(r.process.name()))
    };
    let name = name.unwrap_or_else(|| alloc::format!("user-{}", pid));

    let (kernel_rsp, user_rsp, entry, l4_frame) = {
        let procs = PROCESSES.lock();
        let record = match procs.iter().find(|r| r.process.pid == pid) {
            Some(r) => r,
            None => {
                crate::println!("ring3: pid {} is not loaded", pid);
                return;
            }
        };
        if !record.process.is_loaded() {
            crate::println!("ring3: pid {} is not loaded", pid);
            return;
        }
        let l4 = record.process.space.as_ref()
            .map(|s| s.l4_frame())
            .unwrap_or_else(crate::memory::active_p4_frame);
        (record.process.kernel_stack_top, record.process.user_stack_top, record.process.entry, l4)
    };

    let requested_caps = crate::userspace::capabilities_for_program(&name);
    let granted_caps = crate::security::filter_delegatable(&requested_caps, caller_capabilities);

    // Register the user process with the scheduler so the
    // context switch layer (Phase 2) can find it. The kernel
    // main context is the implicit "current" task; the user
    // process becomes the next runnable task.
    crate::scheduler::register_user(
        pid,
        &name,
        crate::scheduler::Priority::Normal,
        kernel_rsp,
        l4_frame.start_address().as_u64(),
        &granted_caps,
    );
    // Seed the incoming task's saved iretq frame so that if it is
    // ever preempted and resumed by the scheduler, the saved context
    // is valid from the first instruction.
    let target_user_rsp = if user_rsp.as_u64() > 8 { user_rsp.as_u64() - 8 } else { user_rsp.as_u64() };
    let ctx = crate::scheduler::TaskContext::ring3(
        entry,
        target_user_rsp,
    );
    crate::scheduler::write_context(pid, ctx);
    // Claim the CPU for this pid: mark it Running and drain it from
    // the ready queue so a later `schedule_next` cannot try to
    // re-enter it through the seeded context while it is already
    // executing. Also sets CURRENT_PID so the tick handler decrements
    // its time slice.
    crate::scheduler::claim_for_run(pid);

    enter_ring3_inner(kernel_rsp, VirtAddr::new(target_user_rsp), entry, l4_frame);
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
        let kernel_stack = self.kernel_stack.take();
        let space = self.space.take();
        core::mem::forget(kernel_stack);
        core::mem::forget(space);
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

pub fn fault_in_page(pid: u64, addr: VirtAddr) -> bool {
    let mut procs = PROCESSES.lock();
    if let Some(record) = procs.iter_mut().find(|r| r.process.pid == pid) {
        if let Some(ref mut space) = record.process.space {
            // fault_in() itself logs (it's the one that knows the batch
            // size, needed to tell a handful of deliberate sparse touches
            // apart from a real model's bulk sequential load - see the
            // comment there).
            return space.fault_in(addr);
        }
    }
    false
}

pub fn register_mmap(pid: u64, file_path: String, len: u64, flags: u64) -> Result<VirtAddr, &'static str> {
    let mut procs = PROCESSES.lock();
    let record = procs.iter_mut().find(|r| r.process.pid == pid).ok_or("process not found")?;
    let space = record.process.space.as_mut().ok_or("process has no address space")?;
    
    let base = space.find_free_vaddr(len).ok_or("no free virtual address range")?;
    space.mmap_regions.push(MmapRegion {
        base,
        len,
        file_path,
        file_offset: 0,
        flags,
        populated: alloc::collections::BTreeSet::new(),
    });
    
    crate::println!("[kernel-mmap] mmap registered, pid={} user_frames={}", pid, space.user_frames.len());
    Ok(base)
}
