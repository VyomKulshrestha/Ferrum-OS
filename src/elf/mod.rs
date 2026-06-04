// ============================================================================
// FerrumOS - ELF64 Parser
// ============================================================================
// Minimal ELF64 parser used by the userspace loader (Phase 1.4) and the
// kernel boot-time sanity check. We only consume ET_EXEC and ET_DYN
// binaries for the x86_64 architecture. The parser is intentionally
// allocation-free in the hot path: the caller owns the byte slice and
// the returned descriptor borrows from it.
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use core::fmt;

/// ELF magic number: `0x7F E L F`.
pub const ELF_MAGIC: [u8; 4] = [0x7F, b'E', b'L', b'F'];

/// 64-bit ELF base header size (excluding extended ident).
pub const ELF64_HEADER_SIZE: usize = 64;

/// Size of a 64-bit program header entry.
pub const PROGRAM_HEADER_SIZE: usize = 56;

/// ELF class (we only accept ELFCLASS64).
pub const ELFCLASS64: u8 = 2;

/// Little-endian data encoding.
pub const ELFDATA2LSB: u8 = 1;

/// Current ELF spec version we recognise.
pub const EV_CURRENT: u8 = 1;

/// Machine type for x86_64.
pub const EM_X86_64: u16 = 62;

/// e_type values we accept.
pub const ET_EXEC: u16 = 2;
pub const ET_DYN: u16 = 3;

/// p_type values we care about.
pub const PT_NULL: u32 = 0;
pub const PT_LOAD: u32 = 1;

/// Required segment permission bits.
pub const PF_X: u32 = 0x1;
pub const PF_W: u32 = 0x2;
pub const PF_R: u32 = 0x4;

// ============================================================================
// Header structures
// ============================================================================

/// Decoded ELF64 header. All multi-byte fields are stored in the ELF's
/// native byte order (we only accept little-endian).
#[derive(Debug, Clone, Copy)]
pub struct Elf64Header {
    pub e_type: u16,
    pub e_machine: u16,
    pub e_version: u32,
    pub e_entry: u64,
    pub e_phoff: u64,
    pub e_shoff: u64,
    pub e_flags: u32,
    pub e_ehsize: u16,
    pub e_phentsize: u16,
    pub e_phnum: u16,
    pub e_shentsize: u16,
    pub e_shnum: u16,
    pub e_shstrndx: u16,
}

/// Decoded program header entry.
#[derive(Debug, Clone, Copy)]
pub struct ProgramHeader {
    pub p_type: u32,
    pub p_flags: u32,
    pub p_offset: u64,
    pub p_vaddr: u64,
    pub p_paddr: u64,
    pub p_filesz: u64,
    pub p_memsz: u64,
    pub p_align: u64,
}

impl ProgramHeader {
    pub fn is_load(&self) -> bool {
        self.p_type == PT_LOAD
    }

    pub fn is_executable(&self) -> bool {
        self.p_flags & PF_X != 0
    }

    pub fn is_writable(&self) -> bool {
        self.p_flags & PF_W != 0
    }

    pub fn is_readable(&self) -> bool {
        self.p_flags & PF_R != 0
    }
}

// ============================================================================
// Errors
// ============================================================================

/// Failure modes the parser can produce.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ElfError {
    /// Byte slice is shorter than the 64-byte ELF header.
    TooSmallForHeader,
    /// Bytes 0..4 are not the ELF magic.
    BadMagic,
    /// `ei_class` is not ELFCLASS64.
    NotElf64,
    /// `ei_data` is not ELFDATA2LSB.
    NotLittleEndian,
    /// `ei_version` is not EV_CURRENT.
    UnsupportedVersion,
    /// `e_machine` is not EM_X86_64.
    UnsupportedMachine,
    /// `e_type` is not ET_EXEC or ET_DYN.
    UnsupportedType,
    /// `e_phentsize` does not match the size we expect.
    BadProgramHeaderSize,
    /// Program header table extends past the input slice.
    ProgramHeadersOutOfRange,
    /// A PT_LOAD segment's bytes extend past the input slice.
    LoadSegmentOutOfRange,
    /// Two PT_LOAD segments overlap, or a later one starts before an
    /// earlier one. The kernel loader cannot handle either.
    OverlappingLoadSegments,
    /// A PT_LOAD segment's `p_memsz` is smaller than `p_filesz`.
    InvertedLoadSegment,
}

impl fmt::Display for ElfError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooSmallForHeader => f.write_str("input smaller than ELF64 header"),
            Self::BadMagic => f.write_str("missing ELF magic"),
            Self::NotElf64 => f.write_str("not an ELFCLASS64 binary"),
            Self::NotLittleEndian => f.write_str("not a little-endian ELF"),
            Self::UnsupportedVersion => f.write_str("unsupported ELF version"),
            Self::UnsupportedMachine => f.write_str("unsupported e_machine (need EM_X86_64)"),
            Self::UnsupportedType => f.write_str("unsupported e_type (need ET_EXEC or ET_DYN)"),
            Self::BadProgramHeaderSize => f.write_str("e_phentsize does not match 56"),
            Self::ProgramHeadersOutOfRange => {
                f.write_str("program header table extends past input")
            }
            Self::LoadSegmentOutOfRange => {
                f.write_str("a PT_LOAD segment's bytes extend past input")
            }
            Self::OverlappingLoadSegments => {
                f.write_str("PT_LOAD segments overlap or are out of order")
            }
            Self::InvertedLoadSegment => f.write_str("p_memsz < p_filesz on a PT_LOAD segment"),
        }
    }
}

// ============================================================================
// Parsed ELF
// ============================================================================

/// A successfully parsed ELF64 binary.
#[derive(Debug, Clone)]
pub struct Elf<'a> {
    header: Elf64Header,
    program_headers: Vec<ProgramHeader>,
    raw: &'a [u8],
}

impl<'a> Elf<'a> {
    pub fn entry(&self) -> u64 {
        self.header.e_entry
    }

    pub fn header(&self) -> &Elf64Header {
        &self.header
    }

    pub fn program_headers(&self) -> &[ProgramHeader] {
        &self.program_headers
    }

    /// Iterator over PT_LOAD segments in the order they appear in the
    /// program header table. The kernel loader uses this to map each
    /// segment into the new address space.
    pub fn load_segments(&self) -> impl Iterator<Item = &ProgramHeader> {
        self.program_headers
            .iter()
            .filter(|ph| ph.is_load())
    }

    /// Raw bytes for a PT_LOAD segment. Returns `None` if the segment is
    /// not PT_LOAD or the input slice did not contain enough bytes (which
    /// `parse` would normally reject; this is a defensive accessor for
    /// callers that synthesise descriptors).
    pub fn segment_bytes(&self, ph: &ProgramHeader) -> Option<&'a [u8]> {
        if ph.p_type != PT_LOAD {
            return None;
        }
        let start = ph.p_offset as usize;
        let end = start.saturating_add(ph.p_filesz as usize);
        if end > self.raw.len() {
            return None;
        }
        Some(&self.raw[start..end])
    }

    /// Lowest virtual address referenced by any PT_LOAD segment.
    pub fn load_vaddr_min(&self) -> Option<u64> {
        self.load_segments().map(|ph| ph.p_vaddr).min()
    }

    /// Highest virtual address (exclusive) referenced by any PT_LOAD
    /// segment when sized by `p_memsz`.
    pub fn load_vaddr_max(&self) -> Option<u64> {
        self.load_segments()
            .map(|ph| ph.p_vaddr.saturating_add(ph.p_memsz))
            .max()
    }
}

// ============================================================================
// Public entry point
// ============================================================================

/// Parse a 64-bit ELF from a raw byte slice.
pub fn parse(bytes: &[u8]) -> Result<Elf<'_>, ElfError> {
    if bytes.len() < ELF64_HEADER_SIZE {
        return Err(ElfError::TooSmallForHeader);
    }

    // Magic + class + data + version
    if bytes[0..4] != ELF_MAGIC {
        return Err(ElfError::BadMagic);
    }
    if bytes[4] != ELFCLASS64 {
        return Err(ElfError::NotElf64);
    }
    if bytes[5] != ELFDATA2LSB {
        return Err(ElfError::NotLittleEndian);
    }
    if bytes[6] != EV_CURRENT {
        return Err(ElfError::UnsupportedVersion);
    }

    // All multi-byte fields are little-endian, so we can read them as
    // native u16/u32/u64 on x86_64. If we ever move to big-endian
    // hardware, this needs explicit byte-swapping.
    let header = Elf64Header {
        e_type: u16::from_le_bytes([bytes[16], bytes[17]]),
        e_machine: u16::from_le_bytes([bytes[18], bytes[19]]),
        e_version: u32::from_le_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]),
        e_entry: u64::from_le_bytes([
            bytes[24], bytes[25], bytes[26], bytes[27], bytes[28], bytes[29], bytes[30], bytes[31],
        ]),
        e_phoff: u64::from_le_bytes([
            bytes[32], bytes[33], bytes[34], bytes[35], bytes[36], bytes[37], bytes[38], bytes[39],
        ]),
        e_shoff: u64::from_le_bytes([
            bytes[40], bytes[41], bytes[42], bytes[43], bytes[44], bytes[45], bytes[46], bytes[47],
        ]),
        e_flags: u32::from_le_bytes([bytes[48], bytes[49], bytes[50], bytes[51]]),
        e_ehsize: u16::from_le_bytes([bytes[52], bytes[53]]),
        e_phentsize: u16::from_le_bytes([bytes[54], bytes[55]]),
        e_phnum: u16::from_le_bytes([bytes[56], bytes[57]]),
        e_shentsize: u16::from_le_bytes([bytes[58], bytes[59]]),
        e_shnum: u16::from_le_bytes([bytes[60], bytes[61]]),
        e_shstrndx: u16::from_le_bytes([bytes[62], bytes[63]]),
    };

    if header.e_machine != EM_X86_64 {
        return Err(ElfError::UnsupportedMachine);
    }
    if header.e_type != ET_EXEC && header.e_type != ET_DYN {
        return Err(ElfError::UnsupportedType);
    }
    if header.e_phentsize as usize != PROGRAM_HEADER_SIZE {
        return Err(ElfError::BadProgramHeaderSize);
    }

    // Walk the program header table. We collect every entry (including
    // non-PT_LOAD) so callers can introspect, but we also validate that
    // the table fits inside the input buffer.
    let phoff = header.e_phoff as usize;
    let phnum = header.e_phnum as usize;
    let ph_table_end = phoff
        .checked_add(phnum.saturating_mul(PROGRAM_HEADER_SIZE))
        .ok_or(ElfError::ProgramHeadersOutOfRange)?;
    if ph_table_end > bytes.len() {
        return Err(ElfError::ProgramHeadersOutOfRange);
    }

    let mut program_headers = Vec::with_capacity(phnum);
    for index in 0..phnum {
        let base = phoff + index * PROGRAM_HEADER_SIZE;
        let ph = ProgramHeader {
            p_type: u32::from_le_bytes([
                bytes[base],
                bytes[base + 1],
                bytes[base + 2],
                bytes[base + 3],
            ]),
            p_flags: u32::from_le_bytes([
                bytes[base + 4],
                bytes[base + 5],
                bytes[base + 6],
                bytes[base + 7],
            ]),
            p_offset: u64::from_le_bytes([
                bytes[base + 8],
                bytes[base + 9],
                bytes[base + 10],
                bytes[base + 11],
                bytes[base + 12],
                bytes[base + 13],
                bytes[base + 14],
                bytes[base + 15],
            ]),
            p_vaddr: u64::from_le_bytes([
                bytes[base + 16],
                bytes[base + 17],
                bytes[base + 18],
                bytes[base + 19],
                bytes[base + 20],
                bytes[base + 21],
                bytes[base + 22],
                bytes[base + 23],
            ]),
            p_paddr: u64::from_le_bytes([
                bytes[base + 24],
                bytes[base + 25],
                bytes[base + 26],
                bytes[base + 27],
                bytes[base + 28],
                bytes[base + 29],
                bytes[base + 30],
                bytes[base + 31],
            ]),
            p_filesz: u64::from_le_bytes([
                bytes[base + 32],
                bytes[base + 33],
                bytes[base + 34],
                bytes[base + 35],
                bytes[base + 36],
                bytes[base + 37],
                bytes[base + 38],
                bytes[base + 39],
            ]),
            p_memsz: u64::from_le_bytes([
                bytes[base + 40],
                bytes[base + 41],
                bytes[base + 42],
                bytes[base + 43],
                bytes[base + 44],
                bytes[base + 45],
                bytes[base + 46],
                bytes[base + 47],
            ]),
            p_align: u64::from_le_bytes([
                bytes[base + 48],
                bytes[base + 49],
                bytes[base + 50],
                bytes[base + 51],
                bytes[base + 52],
                bytes[base + 53],
                bytes[base + 54],
                bytes[base + 55],
            ]),
        };
        program_headers.push(ph);
    }

    // Validate every PT_LOAD segment. We do this in a separate pass so
    // we can also enforce the kernel loader's "no overlap, in address
    // order" requirement.
    let mut previous_end: u64 = 0;
    let mut seen_load = false;
    for ph in &program_headers {
        if ph.p_type != PT_LOAD {
            continue;
        }
        if ph.p_memsz < ph.p_filesz {
            return Err(ElfError::InvertedLoadSegment);
        }
        let start = ph.p_offset as usize;
        let end = start
            .checked_add(ph.p_filesz as usize)
            .ok_or(ElfError::LoadSegmentOutOfRange)?;
        if end > bytes.len() {
            return Err(ElfError::LoadSegmentOutOfRange);
        }
        let vaddr_start = ph.p_vaddr;
        let vaddr_end = ph.p_vaddr.saturating_add(ph.p_memsz);
        if seen_load && vaddr_start < previous_end {
            return Err(ElfError::OverlappingLoadSegments);
        }
        previous_end = vaddr_end;
        seen_load = true;
    }

    Ok(Elf {
        header,
        program_headers,
        raw: bytes,
    })
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a synthetic ELF64 byte slice with the given program headers.
    /// Each PT_LOAD segment is backed by zeroed bytes; the caller can
    /// assert on the parsed descriptor without needing a real toolchain.
    fn synth_elf(entry: u64, loads: &[(u64, u64, u32)]) -> Vec<u8> {
        let mut bytes = vec![0u8; 64 + loads.len() * PROGRAM_HEADER_SIZE];
        bytes[0..4].copy_from_slice(&ELF_MAGIC);
        bytes[4] = ELFCLASS64;
        bytes[5] = ELFDATA2LSB;
        bytes[6] = EV_CURRENT;
        bytes[16..18].copy_from_slice(&ET_EXEC.to_le_bytes());
        bytes[18..20].copy_from_slice(&EM_X86_64.to_le_bytes());
        bytes[20..24].copy_from_slice(&1u32.to_le_bytes());
        bytes[24..32].copy_from_slice(&entry.to_le_bytes());
        bytes[32..40].copy_from_slice(&64u64.to_le_bytes()); // e_phoff
        bytes[52..54].copy_from_slice(&64u16.to_le_bytes()); // e_ehsize
        bytes[54..56].copy_from_slice(&(PROGRAM_HEADER_SIZE as u16).to_le_bytes());
        bytes[56..58].copy_from_slice(&(loads.len() as u16).to_le_bytes());

        for (i, (vaddr, memsz, flags)) in loads.iter().enumerate() {
            let base = 64 + i * PROGRAM_HEADER_SIZE;
            bytes[base..base + 4].copy_from_slice(&PT_LOAD.to_le_bytes());
            bytes[base + 4..base + 8].copy_from_slice(&flags.to_le_bytes());
            bytes[base + 16..base + 24].copy_from_slice(&vaddr.to_le_bytes());
            bytes[base + 32..base + 40].copy_from_slice(&memsz.to_le_bytes());
            bytes[base + 40..base + 48].copy_from_slice(&memsz.to_le_bytes());
        }

        bytes
    }

    #[test]
    fn rejects_truncated_header() {
        let bytes = vec![0u8; 32];
        assert_eq!(parse(&bytes), Err(ElfError::TooSmallForHeader));
    }

    #[test]
    fn rejects_bad_magic() {
        let mut bytes = vec![0u8; 64];
        bytes[4] = ELFCLASS64;
        bytes[5] = ELFDATA2LSB;
        bytes[6] = EV_CURRENT;
        bytes[18..20].copy_from_slice(&EM_X86_64.to_le_bytes());
        assert_eq!(parse(&bytes), Err(ElfError::BadMagic));
    }

    #[test]
    fn rejects_non_64bit() {
        let mut bytes = vec![0u8; 64];
        bytes[0..4].copy_from_slice(&ELF_MAGIC);
        bytes[4] = 1; // ELFCLASS32
        assert_eq!(parse(&bytes), Err(ElfError::NotElf64));
    }

    #[test]
    fn rejects_big_endian() {
        let mut bytes = vec![0u8; 64];
        bytes[0..4].copy_from_slice(&ELF_MAGIC);
        bytes[4] = ELFCLASS64;
        bytes[5] = 2; // ELFDATA2MSB
        assert_eq!(parse(&bytes), Err(ElfError::NotLittleEndian));
    }

    #[test]
    fn rejects_non_x86_64() {
        let mut bytes = synth_elf(0, &[]);
        bytes[18..20].copy_from_slice(&3u16.to_le_bytes()); // EM_386
        assert_eq!(parse(&bytes), Err(ElfError::UnsupportedMachine));
    }

    #[test]
    fn parses_minimal_elf() {
        let bytes = synth_elf(0x400000, &[(0x400000, 0x1000, PF_R | PF_X)]);
        let elf = parse(&bytes).expect("parse should succeed");
        assert_eq!(elf.entry(), 0x400000);
        let loads: Vec<_> = elf.load_segments().collect();
        assert_eq!(loads.len(), 1);
        assert_eq!(loads[0].p_vaddr, 0x400000);
        assert_eq!(loads[0].p_memsz, 0x1000);
    }

    #[test]
    fn rejects_overlapping_segments() {
        // Two PT_LOAD segments with the first ending after the second
        // starts: kernel loader cannot map this.
        let bytes = synth_elf(
            0x400000,
            &[
                (0x400000, 0x2000, PF_R | PF_X),
                (0x400500, 0x1000, PF_R | PF_W),
            ],
        );
        assert_eq!(parse(&bytes), Err(ElfError::OverlappingLoadSegments));
    }

    #[test]
    fn rejects_inverted_segment() {
        // p_memsz < p_filesz is invalid; the kernel loader will
        // mis-truncate the segment.
        let bytes = synth_elf(0x400000, &[(0x400000, 0x100, PF_R)]);
        let mut bytes = bytes;
        // Overwrite p_memsz with a smaller value (0x10) on the first
        // PT_LOAD segment.  p_filesz stays at 0x100.
        let base = 64;
        bytes[base + 40..base + 48].copy_from_slice(&0x10u64.to_le_bytes());
        assert_eq!(parse(&bytes), Err(ElfError::InvertedLoadSegment));
    }

    #[test]
    fn segment_bytes_round_trip() {
        let mut bytes = synth_elf(0x400000, &[(0x400000, 0x10, PF_R)]);
        // Write a known byte into the segment's file bytes.
        let segment_offset = 64 + PROGRAM_HEADER_SIZE;
        bytes[segment_offset] = 0xCC;
        let elf = parse(&bytes).expect("parse should succeed");
        let loads: Vec<_> = elf.load_segments().collect();
        let bytes = elf.segment_bytes(loads[0]).expect("bytes");
        assert_eq!(bytes[0], 0xCC);
        assert_eq!(bytes.len(), 0x10);
    }

    #[test]
    fn load_vaddr_range_is_correct() {
        let bytes = synth_elf(
            0x400000,
            &[
                (0x400000, 0x1000, PF_R | PF_X),
                (0x401000, 0x500, PF_R | PF_W),
            ],
        );
        let elf = parse(&bytes).expect("parse should succeed");
        assert_eq!(elf.load_vaddr_min(), Some(0x400000));
        assert_eq!(elf.load_vaddr_max(), Some(0x401500));
    }
}
