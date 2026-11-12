// ============================================================================
// FerrumOS - Kernel self-tests, fi2 gate policy (workstream P)
// ============================================================================
// `test-syscall <name>` reaches these after every earlier self-test file. Each
// prints `selftest <name>: key=value ...` lines that
// `scripts/verify_gate_policy.mjs` checks. They drive the same kernel
// functions a ring-3 caller reaches and clean up after themselves.
//
//   hook-dir         the shell-only directory of the daemon's startup hooks (Q4)
//   audit-quota      one source cannot push another's unflushed entries out (Q6)
//   audit-quota-off  the same with the quota switched off (negative control)
//   focus-target     typed text bound to the focused window (Q-J2c)
//   service-query    SystemQuery type 5 names the registered services (Q5)
// ============================================================================

extern crate alloc;

use crate::println;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

/// Pids no process can hold (see selftest.rs), one per role.
const TEST_PID: u64 = u64::MAX - 1000;
const VICTIM: u64 = u64::MAX - 1001;
const FLOODER: u64 = u64::MAX - 1002;

pub fn run(name: &str) -> bool {
    match name {
        "hook-dir" => hook_dir(),
        "audit-quota" => audit_quota(true),
        "audit-quota-off" => audit_quota(false),
        "focus-target" => focus_target(),
        "service-query" => service_query(),
        _ => return false,
    }
    true
}

/// fi2 Q4: /tmp/heliox-hooks exists at boot, every spelling of a path in it
/// is shell-only, and the kernel shell itself can still create a trigger.
fn hook_dir() {
    use crate::syscall::fs::is_shell_only_path;
    let exists = crate::fs::list_dir(crate::syscall::fs::SHELL_ONLY_DIR).is_ok();
    let covered = [
        "/tmp/heliox-hooks",
        "/tmp/heliox-hooks/net_test",
        "//tmp//heliox-hooks//world_model_collect",
        "/tmp/heliox-hooks/a/b",
    ]
    .iter()
    .all(|path| is_shell_only_path(path));
    let not_covered = ["/tmp/net_test", "/tmp/heliox-hooks2/x", "/disk/tmp/heliox-hooks/x", "/TMP/heliox-hooks/x"]
        .iter()
        .all(|path| !is_shell_only_path(path));
    let trigger = "/tmp/heliox-hooks/selftest-trigger";
    let shell_can_write = crate::fs::create_file(trigger, "1").is_ok();
    let removed = crate::fs::remove(trigger).is_ok();
    println!(
        "selftest hook-dir: exists={} covered={} not_covered={} shell_can_write={} removed={}",
        exists, covered, not_covered, shell_can_write, removed
    );
}

/// fi2 Q6: a victim's ten unflushed entries survive a flood of 300 entries
/// from another source, and the flooder holds at most its share. With the
/// quota off (negative control) the flood pushes the victim's entries out.
fn audit_quota(quota: bool) {
    use crate::logging::audit::{self, AuditEvent};
    let label = if quota { "audit-quota" } else { "audit-quota-off" };
    let was = audit::SOURCE_QUOTA.swap(quota, Ordering::SeqCst);
    let tag = crate::scheduler::total_ticks();
    let victim_messages: Vec<alloc::string::String> = (0..10)
        .map(|i| alloc::format!("selftest {} victim {} {}", label, tag, i))
        .collect();
    for message in &victim_messages {
        audit::log_event_from(VICTIM, AuditEvent::UserAudit, message);
    }
    let dropped_before = audit::UNFLUSHED_DROPPED.load(Ordering::SeqCst);
    for i in 0..300 {
        audit::log_event_from(
            FLOODER,
            AuditEvent::UserAudit,
            &alloc::format!("selftest {} flood {} {}", label, tag, i),
        );
    }
    let victim_kept = victim_messages.iter().filter(|m| audit::holds(VICTIM, m)).count();
    let flooder_unflushed = audit::unflushed_from(FLOODER);
    let total = audit::total_entries();
    audit::SOURCE_QUOTA.store(was, Ordering::SeqCst);
    println!(
        "selftest {}: victim_kept={}/10 flooder_unflushed={} flooder_within_share={} total={} within_ring={} dropped={}",
        label,
        victim_kept,
        flooder_unflushed,
        flooder_unflushed <= audit::PER_SOURCE_UNFLUSHED,
        total,
        total <= audit::MAX_ENTRIES,
        audit::UNFLUSHED_DROPPED.load(Ordering::SeqCst).saturating_sub(dropped_before)
    );
}

/// fi2 Q-J2c: InjectKey bound to the focused window (args[1] = 1) is
/// delivered while that window has focus, refused at once for another
/// window, and dropped by the desktop if focus moves before it is processed.
fn focus_target() {
    use crate::gui::compositor::COMPOSITOR;
    let was_primed = crate::gui::cursor::input_primed();
    let (saved_order, saved_focus): (Vec<u64>, Option<u64>) = {
        let state = COMPOSITOR.lock();
        (
            state.windows.iter().map(|window| window.id).collect(),
            state.focused_idx.and_then(|idx| state.windows.get(idx)).map(|window| window.id),
        )
    };
    crate::input::discard_stale_keyboard_events();
    crate::gui::cursor::process_input();

    let window_id = crate::syscall::gui_window::create_window_for(TEST_PID, "selftest-focus", 96, 48).value;
    let focus_on = |id: Option<u64>| {
        let mut state = COMPOSITOR.lock();
        state.focused_idx = id.and_then(|id| state.windows.iter().position(|window| window.id == id));
    };
    let inject = |window: u64, owner: u64| {
        crate::syscall::input::sys_inject_key([b'q' as u64, 1, window, owner, 0, 0])
    };
    let drain = || while crate::gui::app_window::poll_input(window_id, TEST_PID).is_some() {};

    focus_on(Some(window_id));
    let target = crate::gui::compositor::focus_target();
    let target_ok = target.window == window_id && target.owner == TEST_PID && target.rel_x == 0;

    // 1. Focus on the approved window: the key is delivered, marked.
    drain();
    let r = inject(window_id, TEST_PID);
    crate::gui::cursor::process_input();
    let event = crate::gui::app_window::poll_input(window_id, TEST_PID);
    drain();
    let delivered = r.status == crate::syscall::SyscallStatus::Ok
        && event.map(|e| e.tag == 0 && e.a == b'q' as u32 && e.injected).unwrap_or(false);

    // 2. Bound to another window (or owner): refused at once.
    let refused_other = inject(window_id + 1_000_000, TEST_PID).status == crate::syscall::SyscallStatus::VersionMismatch
        && inject(window_id, TEST_PID + 1).status == crate::syscall::SyscallStatus::VersionMismatch
        && inject(0, 0).status == crate::syscall::SyscallStatus::VersionMismatch;

    // 3. Accepted, then focus moves before the desktop processes it: dropped.
    let dropped_before = crate::input::GUARDED_KEYS_DROPPED.load(Ordering::SeqCst);
    let r = inject(window_id, TEST_PID);
    focus_on(None);
    crate::gui::cursor::process_input();
    let dropped_later = r.status == crate::syscall::SyscallStatus::Ok
        && crate::input::GUARDED_KEYS_DROPPED.load(Ordering::SeqCst) >= dropped_before + 2;
    let not_delivered = crate::gui::app_window::poll_input(window_id, TEST_PID).is_none();

    // 4. Nothing focused: FocusTarget reports window 0.
    let none_reported = crate::gui::compositor::focus_target().window == 0;

    crate::gui::app_window::close_for_pid(TEST_PID);
    {
        let mut state = COMPOSITOR.lock();
        let mut windows = core::mem::take(&mut state.windows);
        windows.retain(|window| saved_order.contains(&window.id));
        windows.sort_by_key(|window| saved_order.iter().position(|id| *id == window.id));
        state.focused_idx = saved_focus.and_then(|id| windows.iter().position(|window| window.id == id));
        state.windows = windows;
        state.needs_redraw = true;
    }
    crate::gui::cursor::set_input_primed(was_primed);
    println!(
        "selftest focus-target: target_ok={} delivered={} refused_other={} dropped_later={} not_delivered={} none_reported={}",
        target_ok, delivered, refused_other, dropped_later, not_delivered, none_reported
    );
}

/// fi2 Q5: SystemQuery type 5 lists every registered service by id and name.
fn service_query() {
    let services = crate::services::list_services();
    let result = crate::syscall::query::query_services_for_test();
    let all_named = services
        .iter()
        .all(|service| result.contains(&alloc::format!("{{\"id\":{},\"name\":\"", service.id)));
    println!(
        "selftest service-query: services={} all_named={} json_array={}",
        services.len(),
        all_named,
        result.starts_with('[') && result.ends_with(']')
    );
}
