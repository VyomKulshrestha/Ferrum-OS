use alloc::string::String;
use alloc::vec::Vec;
use crate::println;

#[derive(Debug)]
pub struct RuntimeService {
    pub name: String,
    pub pid: u64,
    pub restart_count: u32,
    pub path: String,
}

pub struct Supervisor {
    pub services: Vec<RuntimeService>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            services: Vec::new(),
        }
    }

    pub fn register(&mut self, name: &str, path: &str) {
        // In a real implementation, we would spawn the process here and get a PID
        let fake_pid = self.services.len() as u64 + 10;
        
        self.services.push(RuntimeService {
            name: String::from(name),
            pid: fake_pid,
            restart_count: 0,
            path: String::from(path),
        });
        
        println!("[ PID 1] Registered service: {} (PID: {})", name, fake_pid);
    }

    pub fn supervise_loop(&mut self) -> ! {
        println!("[ PID 1] Entering persistent supervision loop");
        
        loop {
            // Wait for any child process to exit
            // We simulate waiting here for Phase 5 scaffolding
            let exited_pid = self.wait_any();
            
            if let Some(service) = self.services.iter_mut().find(|s| s.pid == exited_pid) {
                println!("[ PID 1] Service '{}' (PID {}) exited abnormally", service.name, service.pid);
                
                service.restart_count += 1;
                println!("[ PID 1] Restarting '{}' (Attempt {})...", service.name, service.restart_count);
                
                // Re-spawn the service and update PID
                let new_pid = exited_pid + 100;
                service.pid = new_pid;
                
                println!("[ PID 1] Service '{}' respawned as PID {}", service.name, new_pid);
            }
            
            x86_64::instructions::hlt();
        }
    }
    
    fn wait_any(&self) -> u64 {
        // Dummy implementation. In reality, this would invoke `sys_wait` on the kernel.
        // For demonstration, we just return a fake PID.
        0
    }
}
