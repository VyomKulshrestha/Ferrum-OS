; FerrumOS SMP Trampoline
; Loaded to physical address 0x8000
; Started in 16-bit real mode by INIT-SIPI-SIPI
;
; src/smp/mod.rs embeds the assembled trampoline.bin directly via
; include_bytes! - if you change this file, reassemble it with:
;   nasm -f bin trampoline.s -o trampoline.bin

[BITS 16]
[ORG 0x8000]

trampoline_start:
    cli
    cld
    
    ; Set segment registers to 0
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    
    ; Load the 32-bit GDT
    lgdt [gdt32_desc]
    
    ; Enable Protected Mode
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    
    ; Far jump to flush instruction prefetch queue and set CS
    jmp 0x08:protected_mode

[BITS 32]
protected_mode:
    ; Set up data segments
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    
    ; We need to enable 64-bit Long Mode.
    ; 1. Enable PAE
    mov eax, cr4
    or eax, 1 << 5      ; PAE
    mov cr4, eax
    
    ; 2. Load CR3 with the BSP's Page Table
    ; The kernel patches this value at [0x8000 + cr3_value - trampoline_start]
    mov eax, [cr3_value]
    mov cr3, eax
    
    ; 3. Enable Long Mode in EFER MSR
    mov ecx, 0xC0000080
    rdmsr
    or eax, 1 << 8      ; LME
    wrmsr
    
    ; 4. Enable Paging
    mov eax, cr0
    or eax, 1 << 31     ; PG
    mov cr0, eax
    
    ; 5. Load the 64-bit GDT
    lgdt [gdt64_desc]
    
    ; Far jump to 64-bit mode
    jmp 0x08:long_mode

[BITS 64]
long_mode:
    ; Data segments to 0
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax
    
    ; The kernel patches the stack pointer here
    mov rsp, [stack_pointer]
    
    ; The kernel patches the entry point here
    mov rax, [entry_point]
    call rax
    
    ; If we return, halt forever
halt:
    cli
    hlt
    jmp halt

align 8
cr3_value:      dq 0
stack_pointer:  dq 0
entry_point:    dq 0

align 8
gdt32:
    dq 0                        ; Null descriptor
    dq 0x00cf9a000000ffff       ; 32-bit Code
    dq 0x00cf92000000ffff       ; 32-bit Data
gdt32_desc:
    dw $ - gdt32 - 1
    dd gdt32

align 8
gdt64:
    dq 0                        ; Null descriptor
    dq 0x00af9a000000ffff       ; 64-bit Code
    dq 0x00af92000000ffff       ; 64-bit Data
gdt64_desc:
    dw $ - gdt64 - 1
    dd gdt64
