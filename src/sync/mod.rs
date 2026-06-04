use core::sync::atomic::{AtomicUsize, Ordering, AtomicBool};
use core::cell::UnsafeCell;
use core::ops::{Deref, DerefMut};
use crate::println;

/// A simple deadlock-detecting spinlock.
/// In a real SMP system, this would track the APIC ID of the owning core.
/// For v0.1, we track a basic timeout to catch unreleased locks.
pub struct DeadlockMutex<T> {
    locked: AtomicBool,
    owner_core: AtomicUsize,
    data: UnsafeCell<T>,
}

unsafe impl<T: Send> Sync for DeadlockMutex<T> {}
unsafe impl<T: Send> Send for DeadlockMutex<T> {}

pub struct DeadlockMutexGuard<'a, T> {
    mutex: &'a DeadlockMutex<T>,
}

impl<T> DeadlockMutex<T> {
    pub const fn new(data: T) -> Self {
        Self {
            locked: AtomicBool::new(false),
            owner_core: AtomicUsize::new(usize::MAX),
            data: UnsafeCell::new(data),
        }
    }

    pub fn lock(&self) -> DeadlockMutexGuard<'_, T> {
        let mut attempts = 0;
        let threshold = 10_000_000;

        // Current core ID placeholder (will be replaced by APIC ID reading in full SMP)
        let current_core = 0; 

        while self.locked.compare_exchange_weak(false, true, Ordering::Acquire, Ordering::Relaxed).is_err() {
            attempts += 1;
            if attempts > threshold {
                let owner = self.owner_core.load(Ordering::Relaxed);
                println!("[ PANIC ] Deadlock detected! Core {} is waiting for a lock held by core {}", current_core, owner);
                loop { x86_64::instructions::hlt(); }
            }
            core::hint::spin_loop();
        }

        self.owner_core.store(current_core, Ordering::Relaxed);
        DeadlockMutexGuard { mutex: self }
    }
}

impl<'a, T> Deref for DeadlockMutexGuard<'a, T> {
    type Target = T;
    fn deref(&self) -> &Self::Target {
        unsafe { &*self.mutex.data.get() }
    }
}

impl<'a, T> DerefMut for DeadlockMutexGuard<'a, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        unsafe { &mut *self.mutex.data.get() }
    }
}

impl<'a, T> Drop for DeadlockMutexGuard<'a, T> {
    fn drop(&mut self) {
        self.mutex.owner_core.store(usize::MAX, Ordering::Relaxed);
        self.mutex.locked.store(false, Ordering::Release);
    }
}
