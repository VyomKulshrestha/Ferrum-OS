use x86_64::instructions::port::Port;
use spin::Mutex;

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
    last_tick: u64,
}

impl MouseState {
    const fn new() -> Self {
        MouseState {
            cycle: 0,
            packet: [0; 3],
            last_tick: 0,
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
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut cmd_port = Port::<u8>::new(PS2_CMD);
        let mut data_port = Port::<u8>::new(PS2_DATA);

        // Flush any pending data in the PS/2 controller before init
        while (unsafe { cmd_port.read() } & 1) == 1 {
            unsafe { data_port.read() };
        }

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
    });
}

pub fn handle_interrupt() {
    let mut cmd_port = Port::<u8>::new(PS2_CMD);
    let mut data_port = Port::<u8>::new(PS2_DATA);

    loop {
        let status = unsafe { cmd_port.read() };
        // Bit 0 = Output Buffer Full
        if (status & 0x01) == 0 {
            break;
        }
        // Bit 5 = Mouse Output Buffer Full
        if (status & 0x20) == 0 {
            break; // Keyboard byte, leave it for IRQ1
        }

        let data = unsafe { data_port.read() };
        let mut state = MOUSE_STATE.lock();
        
        let now = crate::scheduler::total_ticks();
        if state.cycle > 0 && now.saturating_sub(state.last_tick) > 10 {
            // Desynchronized (timeout of ~200ms). Reset.
            state.cycle = 0;
        }
        state.last_tick = now;
        
        match state.cycle {
            0 => {
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
                let mut dx = state.packet[1] as i16;
                let mut dy = state.packet[2] as i16;

                // Sign extend using the flags register (bit 4 = X sign, bit 5 = Y sign)
                if (flags & 0x10) != 0 {
                    dx -= 256;
                }
                if (flags & 0x20) != 0 {
                    dy -= 256;
                }

                let buttons = flags & 0x07;
                
                // dy is positive for UP in PS/2, so we negate it for screen coordinates
                crate::input::inject_mouse_event(dx as i8, dy.saturating_neg() as i8, buttons);
            }
            _ => state.cycle = 0,
        }
    }
}
