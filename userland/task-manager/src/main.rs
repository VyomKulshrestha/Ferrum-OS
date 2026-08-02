// ============================================================================
// FerrumOS - Task Manager
// ============================================================================
#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();
static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

const CANVAS_W: u32 = 470;
const CANVAS_H: u32 = 380;
const ROW_H: u32 = 36;

#[derive(Clone)]
struct TaskInfo {
    pid: u64,
    name: String,
    state: String,
    priority: String,
    ticks: u64,
}

fn field<'a>(object: &'a str, key: &str) -> Option<&'a str> {
    let needle = alloc::format!("\"{}\":", key);
    let rest = object.split_once(&needle)?.1;
    if let Some(quoted) = rest.strip_prefix('"') {
        Some(quoted.split_once('"')?.0)
    } else {
        Some(rest.split(|ch| ch == ',' || ch == '}').next()?.trim())
    }
}

fn load_tasks(self_pid: u64) -> Vec<TaskInfo> {
    let Some(bytes) = ferrumgui::system_query(1, 16 * 1024) else { return Vec::new() };
    let text = String::from_utf8_lossy(&bytes);
    let mut tasks = Vec::new();
    for object in text.split('{').skip(1) {
        let Some(object) = object.split_once('}').map(|pair| pair.0) else { continue };
        let Some(pid) = field(object, "pid").and_then(|value| value.parse::<u64>().ok()) else { continue };
        let state = field(object, "state").unwrap_or("Unknown");
        if pid == self_pid || state == "Dead" { continue; }
        tasks.push(TaskInfo {
            pid,
            name: field(object, "name").unwrap_or("unknown").to_string(),
            state: state.to_string(),
            priority: field(object, "priority").unwrap_or("?").to_string(),
            ticks: field(object, "ticks").and_then(|value| value.parse().ok()).unwrap_or(0),
        });
    }
    tasks.reverse();
    tasks
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

fn row_rect(index: usize) -> (u32, u32, u32, u32) {
    (8, 48 + index as u32 * ROW_H, CANVAS_W - 16, ROW_H - 4)
}

fn redraw(canvas: &mut Canvas, tasks: &[TaskInfo], selected: Option<usize>, status: &str) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(10, 10, "Task Manager", 0x00, 0xCC, 0xFF);
    canvas.fill_rect(278, 6, 82, 26, 0x22, 0x28, 0x32);
    canvas.draw_string(290, 14, "Refresh", 0xDD, 0xDD, 0xDD);
    canvas.fill_rect(370, 6, 90, 26, 0x52, 0x24, 0x28);
    canvas.draw_string(380, 14, "End task", 0xFF, 0xDD, 0xDD);
    canvas.draw_string(12, 36, "PID   NAME                 STATE      PRIORITY   TICKS", 0x88, 0x99, 0xAA);

    for (index, task) in tasks.iter().take(8).enumerate() {
        let (x, y, w, h) = row_rect(index);
        let (r, g, b) = if selected == Some(index) { (0x28, 0x48, 0x50) } else { (0x1E, 0x22, 0x2C) };
        canvas.fill_rect(x, y, w, h, r, g, b);
        canvas.draw_string(x + 6, y + 10, &alloc::format!("{}", task.pid), 0xDD, 0xDD, 0xDD);
        canvas.draw_string(x + 52, y + 10, &task.name.chars().take(18).collect::<String>(), 0xEE, 0xEE, 0xEE);
        canvas.draw_string(x + 212, y + 10, &task.state, 0xAA, 0xCC, 0xAA);
        canvas.draw_string(x + 302, y + 10, &task.priority, 0xAA, 0xAA, 0xCC);
        canvas.draw_string(x + 390, y + 10, &alloc::format!("{}", task.ticks), 0x99, 0x99, 0x99);
    }
    canvas.draw_string(10, CANVAS_H - 18, status, 0xDD, 0xCC, 0x55);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe { ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len()); }
    let self_pid = ferrumgui::get_pid();
    ferrumgui::write_console("[task-manager] alive pid=");
    ferrumgui::write_int(self_pid as i64);
    ferrumgui::write_console("\n");
    if ferrumgui::process_kill(self_pid) {
        ferrumgui::write_console("[task-manager] ERROR self-kill was allowed\n");
    } else {
        ferrumgui::write_console("[task-manager] self-kill denied as expected\n");
    }
    let window_id = ferrumgui::create_window("Task Manager", CANVAS_W, CANVAS_H);
    let mut tasks = load_tasks(self_pid);
    ferrumgui::write_console("[task-manager] loaded tasks=");
    ferrumgui::write_int(tasks.len() as i64);
    ferrumgui::write_console("\n");
    let mut selected = None;
    let mut status = String::from("Select a non-critical task to end it");
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &tasks, selected, &status);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 { continue; }
            if point_in(c, d, (278, 6, 82, 26)) {
                tasks = load_tasks(self_pid);
                selected = None;
                status = String::from("Task list refreshed");
                ferrumgui::write_console("[task-manager] refreshed\n");
                dirty = true;
                continue;
            }
            if point_in(c, d, (370, 6, 90, 26)) {
                if let Some(index) = selected {
                    if let Some(task) = tasks.get(index).cloned() {
                        if ferrumgui::process_kill(task.pid) {
                            ferrumgui::write_console("[task-manager] ended pid=");
                            ferrumgui::write_int(task.pid as i64);
                            ferrumgui::write_console("\n");
                            status = alloc::format!("Ended {} (pid {})", task.name, task.pid);
                            tasks = load_tasks(self_pid);
                            selected = None;
                        } else {
                            status = String::from("Protected task cannot be ended");
                        }
                    }
                } else {
                    status = String::from("Select a task first");
                }
                dirty = true;
                continue;
            }
            for index in 0..tasks.len().min(8) {
                if point_in(c, d, row_rect(index)) {
                    selected = Some(index);
                    status = alloc::format!("Selected {} (pid {})", tasks[index].name, tasks[index].pid);
                    dirty = true;
                    break;
                }
            }
        }
        if dirty {
            redraw(&mut canvas, &tasks, selected, &status);
            canvas.present(window_id);
        }
        ferrumgui::sleep(50);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
