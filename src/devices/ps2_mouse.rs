use x86_64::instructions::port::Port;
use spin::Mutex;
use crate::input::inject_mouse_event;

// Ports for PS/2 Controller
const PS2_DATA: u16 = 0x60;
const PS2_CMD: u16 = 0x64;

// Commands
const CMD_ENABLE_AUX: u8 = 0xA8;
const CMD_READ_CONFIG: u8 = 0x20;
const CMD_WRITE_CONFIG: u8 = 0x60;
const CMD_WRITE_AUX: u8 = 0xD4;

// Mouse Commands
const MOUSE_SET_DEFAULTS: u8 = 0xF6;
const MOUSE_ENABLE_PACKETS: u8 = 0xF4;
const MOUSE_ACK: u8 = 0xFA;

static MOUSE_STATE: Mutex<MouseState> = Mutex::new(MouseState::new());

struct MouseState {
    cycle: u8,
    packet: [u8; 3],
}

impl MouseState {
    const fn new() -> Self {
        MouseState {
            cycle: 0,
            packet: [0; 3],
        }
    }
}

fn wait_write() {
    let mut cmd_port = Port::<u8>::new(PS2_CMD);
    for _ in 0..100000 {
        if (unsafe { cmd_port.read() } & 2) == 0 {
            break;
        }
    }
}

fn wait_read() {
    let mut cmd_port = Port::<u8>::new(PS2_CMD);
    for _ in 0..100000 {
        if (unsafe { cmd_port.read() } & 1) == 1 {
            break;
        }
    }
}

fn write_mouse(data: u8) {
    let mut cmd_port = Port::<u8>::new(PS2_CMD);
    let mut data_port = Port::<u8>::new(PS2_DATA);
    
    wait_write();
    unsafe { cmd_port.write(CMD_WRITE_AUX) };
    wait_write();
    unsafe { data_port.write(data) };
    
    wait_read();
    unsafe { data_port.read() }; // ACK
}

pub fn init() {
    let mut cmd_port = Port::<u8>::new(PS2_CMD);
    let mut data_port = Port::<u8>::new(PS2_DATA);

    // 1. Enable Auxiliary Device
    wait_write();
    unsafe { cmd_port.write(CMD_ENABLE_AUX) };

    // 2. Read Configuration Byte
    wait_write();
    unsafe { cmd_port.write(CMD_READ_CONFIG) };
    wait_read();
    let mut config = unsafe { data_port.read() };

    // 3. Enable IRQ12, clear clock disable
    config |= 1 << 1;
    config &= !(1 << 5);

    // 4. Write Configuration Byte
    wait_write();
    unsafe { cmd_port.write(CMD_WRITE_CONFIG) };
    wait_write();
    unsafe { data_port.write(config) };

    // 5. Send Set Defaults
    write_mouse(MOUSE_SET_DEFAULTS);

    // 6. Enable Data Reporting
    write_mouse(MOUSE_ENABLE_PACKETS);
    
    crate::serial_println!("PS/2 Mouse initialized");
}

pub fn handle_interrupt() {
    let mut data_port = Port::<u8>::new(PS2_DATA);
    let data = unsafe { data_port.read() };

    let mut state = MOUSE_STATE.lock();
    match state.cycle {
        0 => {
            // First byte must have bit 3 set
            if (data & 0x08) != 0 {
                state.packet[0] = data;
                state.cycle = 1;
            }
        }
        1 => {
            state.packet[1] = data;
            state.cycle = 2;
        }
        2 => {
            state.packet[2] = data;
            state.cycle = 0;
            
            let flags = state.packet[0];
            
            // Validate packet: overflow bits should be 0
            if (flags & 0xC0) == 0 {
                let dx = state.packet[1] as i8;
                let dy = state.packet[2] as i8;
                
                // Y axis is inverted in PS/2 relative to our screen
                let buttons = flags & 0x07;
                
                // Inject into unified input system!
                // NOTE: dy needs to be inverted (PS/2 is +up, our screen is +down)
                // Actually if PS/2 is +up, moving mouse up means dy is positive.
                // Screen coordinate (0,0) is top-left, so moving up is negative Y.
                // We pass dx, -dy to input subsystem.
                inject_mouse_event(dx, -dy, buttons);
            }
        }
        _ => state.cycle = 0,
    }
}
