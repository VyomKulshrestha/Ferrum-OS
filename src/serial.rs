// ============================================================================
// FerrumOS - Serial Port Driver (UART 16550)
// ============================================================================
// Provides serial output for QEMU debugging.
// Serial output is invaluable during OS development because it doesn't
// depend on the VGA buffer being properly initialized.
// ============================================================================

use lazy_static::lazy_static;
use spin::Mutex;
use uart_16550::SerialPort;

lazy_static! {
    /// Global serial port instance on COM1 (0x3F8)
    /// 
    /// Used for debug output visible in the QEMU terminal.
    pub static ref SERIAL1: Mutex<SerialPort> = {
        // Safety: Port 0x3F8 is the standard COM1 address
        let mut serial_port = unsafe { SerialPort::new(0x3F8) };
        serial_port.init();
        Mutex::new(serial_port)
    };
}

/// Internal serial print function
#[doc(hidden)]
pub fn _print(args: ::core::fmt::Arguments) {
    use core::fmt::Write;
    use x86_64::instructions::interrupts;

    interrupts::without_interrupts(|| {
        SERIAL1.lock().write_fmt(args).expect("Printing to serial failed");
    });
}

/// Print to the host serial port (no newline)
#[macro_export]
macro_rules! serial_print {
    ($($arg:tt)*) => {
        $crate::serial::_print(format_args!($($arg)*));
    };
}

/// Print to the host serial port with newline
#[macro_export]
macro_rules! serial_println {
    () => ($crate::serial_print!("\n"));
    ($fmt:expr) => ($crate::serial_print!(concat!($fmt, "\n")));
    ($fmt:expr, $($arg:tt)*) => ($crate::serial_print!(
        concat!($fmt, "\n"), $($arg)*));
}
