// ============================================================================
// FerrumOS - Network Stack (smoltcp)
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use smoltcp::phy::{Device, DeviceCapabilities, Medium};
use smoltcp::time::Instant;

use crate::net::rtl8139::RTL8139_NIC;

pub struct Rtl8139Device;

impl<'a> Device for Rtl8139Device {
    type RxToken<'b> = RxTokenImpl where Self: 'b;
    type TxToken<'b> = TxTokenImpl where Self: 'b;

    fn receive(&mut self, _timestamp: Instant) -> Option<(Self::RxToken<'_>, Self::TxToken<'_>)> {
        let mut nic = RTL8139_NIC.lock();
        if let Some(nic) = nic.as_mut() {
            if let Some(packet) = nic.receive_packet() {
                return Some((RxTokenImpl(packet), TxTokenImpl));
            }
        }
        None
    }

    fn transmit(&mut self, _timestamp: Instant) -> Option<Self::TxToken<'_>> {
        Some(TxTokenImpl)
    }

    fn capabilities(&self) -> DeviceCapabilities {
        let mut caps = DeviceCapabilities::default();
        caps.max_transmission_unit = 1500;
        caps.max_burst_size = Some(1);
        caps.medium = Medium::Ethernet;
        caps
    }
}

pub struct RxTokenImpl(Vec<u8>);

impl smoltcp::phy::RxToken for RxTokenImpl {
    fn consume<R, F>(mut self, f: F) -> R
    where
        F: FnOnce(&mut [u8]) -> R,
    {
        f(&mut self.0)
    }
}

pub struct TxTokenImpl;

impl smoltcp::phy::TxToken for TxTokenImpl {
    fn consume<R, F>(self, len: usize, f: F) -> R
    where
        F: FnOnce(&mut [u8]) -> R,
    {
        let mut buffer = alloc::vec![0; len];
        let result = f(&mut buffer);

        let mut nic = RTL8139_NIC.lock();
        if let Some(nic) = nic.as_mut() {
            let _ = nic.send_packet(&buffer);
        }

        result
    }
}
