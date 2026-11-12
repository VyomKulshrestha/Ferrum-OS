# Negative control for fi1 kernel round 3: keep every new self-test, harness
# and counter; hold back every fix. Run from the worktree root.
import subprocess
from ed import *

BASE = '8d21d68'
def checkout(path):
    subprocess.check_call(['git', 'checkout', BASE, '--', path], cwd=W)

# Files whose round-3 changes are fixes only.
for f in ['src/input/mod.rs', 'src/fs/mod.rs', 'src/fs/ext2.rs', 'src/syscall/audio.rs',
          'src/net/rtl8139.rs', 'src/memory/heap.rs']:
    checkout(f)

# interrupts: no cld; keyboard queue and PS/2 poll without the interrupt guard.
p = 'src/interrupts/mod.rs'
s = rd(p)
cld = '''        // The SysV ABI requires DF = 0 on every call. Ring 3 controls
        // RFLAGS.DF (`std`), and an interrupt or `int 0x80` does not clear
        // it, so without this the kernel's memcpy/memset (`rep movs`/`stos`)
        // run backwards over memory below their destination. The user's DF
        // is restored by iretq from the saved RFLAGS.
        "cld",
'''
assert s.count(cld) == 2
s = s.replace(cld, '')
wr(p, s)
rep(p, '''    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut queue = KEYBOARD_QUEUE.lock();
        queue.as_mut().and_then(|q| q.pop_front())
    })''', '''    let mut queue = KEYBOARD_QUEUE.lock();
    queue.as_mut().and_then(|q| q.pop_front())''')

# ipc: the old broker, plus the receive call the syscall layer now makes.
checkout('src/ipc/mod.rs')
s = rd('src/ipc/mod.rs')
s += '''
/// negctl stub: the old broker delivers by service name only.
pub fn receive_for_owner(service: &str, _owner: u64) -> Result<Message, IpcError> {
    receive_for_service(service)
}
'''
wr('src/ipc/mod.rs', s)

# process: heap-boxed kernel stacks, no stack guard gap, no mailbox claim.
p = 'src/process/mod.rs'
rep(p, '''    kernel_stack: Option<crate::memory::kstack::KernelStack>,''', '''    kernel_stack: Option<alloc::boxed::Box<[u8; KERNEL_STACK_SIZE]>>,''')
rep(p, '''    let kernel_stack =
        crate::memory::kstack::allocate().ok_or("failed to allocate kernel stack")?;
    let kernel_stack_top = kernel_stack.top();''', '''    let kernel_stack: alloc::boxed::Box<[u8; KERNEL_STACK_SIZE]> = unsafe {
        let layout = core::alloc::Layout::new::<[u8; KERNEL_STACK_SIZE]>();
        let ptr = alloc::alloc::alloc_zeroed(layout);
        if ptr.is_null() {
            return Err("failed to allocate kernel stack");
        }
        alloc::boxed::Box::from_raw(ptr as *mut [u8; KERNEL_STACK_SIZE])
    };
    let kernel_stack_top = VirtAddr::new((kernel_stack.as_ptr() as u64 + KERNEL_STACK_SIZE as u64) & !0xF);''')
rep(p, '''        while candidate + len_aligned <= USER_STACK_BASE - USER_STACK_GUARD {''', '''        while candidate + len_aligned <= 0x80_7000_0000 {''')
rep(p, '''            if ph.p_vaddr < USER_STACK_BASE + USER_STACK_SIZE as u64
                && ph.p_vaddr + ph.p_memsz > USER_STACK_BASE - USER_STACK_GUARD
            {
                return Err("PT_LOAD overlaps the user stack or its guard");
            }''', '')
rep(p, '''    crate::ipc::claim_mailbox(pid, &name);
''', '''    let _ = name;
''')

# syscall/fs: copy_to_user and every output check accept any mapped range.
p = 'src/syscall/fs.rs'
rep(p, '''        if !valid_user_write_range(dst, to_copy) {
            return 0;
        }''', '''        if !valid_user_range(dst, to_copy) {
            return 0;
        }''')
rep(p, '''    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    pid != 0 && crate::process::user_range_is_writable(pid, ptr, len)''', '''    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    pid != 0 && crate::process::user_range_is_mapped(pid, ptr, len)''')

# memory: boot regions stay executable.
p = 'src/memory/mod.rs'
rep(p, '''pub fn harden_boot_regions(boot_info_addr: u64) {
    ensure_nxe();''', '''pub fn harden_boot_regions(boot_info_addr: u64) {
    if core::hint::black_box(true) {
        let _ = boot_info_addr;
        return;
    }
    ensure_nxe();''')

# scheduler: the tick allocates its wake list; no null check.
p = 'src/scheduler/mod.rs'
s = rd(p)
a = s.index('        // Wake sleepers in place. This runs in the timer interrupt: it used')
b = s.index('        // Tick counters and time-slice accounting.')
s = s[:a] + '''        let mut to_wake: Vec<u64> = Vec::new();
        for task in sched.tasks.iter() {
            if task.state == TaskState::Blocked && task.wake_at <= now {
                to_wake.push(task.id);
            }
        }
        for pid in &to_wake {
            if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == *pid) {
                task.state = TaskState::Ready;
                task.wake_at = u64::MAX;
                task.time_remaining = TIME_SLICE_TICKS;
                if task.blocked_on_confirmation {
                    task.blocked_on_confirmation = false;
                    task.confirmation_denied = true;
                }
            }
            let pri = sched
                .tasks
                .iter()
                .find(|t| t.id == *pid)
                .map(|t| t.priority.index())
                .unwrap_or(0);
            if !sched.run_queues[pri].contains(pid) {
                sched.run_queues[pri].push_back(*pid);
            }
        }
        drop(to_wake);

''' + s[b:]
wr(p, s)
# exceptions: the missing gates and unmasked PIC lines.
p = 'src/interrupts/mod.rs'
s = rd(p)
a = s.index('        // Every other exception ring 3 can raise.')
END = '        idt[PIC_1_OFFSET + 7].set_handler_fn(spurious_irq7_handler);' + chr(10)
b = s.index(END) + len(END)
s = s[:a] + s[b:]
wr(p, s)
s = rd('src/lib.rs')
a = s.index('    // Unmask only the lines that have a handler')
END = 'write_masks(0xF8, 0x3F) };' + chr(10)
b = s.index(END) + len(END)
wr('src/lib.rs', s[:a] + s[b:])
print('negctl applied')
