#![cfg_attr(not(test), no_std)]

//! Typed, signed and expiring neural-intent contracts.
//!
//! Raw EEG never enters this crate. A host/Ring-3 decoder emits a fixed binary
//! envelope; this library verifies provenance and converts it into proposal-only
//! evidence. It contains no syscall or execution surface.

use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};

pub const NEURAL_INTENT_MAGIC: [u8; 4] = *b"NIV1";
pub const NEURAL_INTENT_SCHEMA_VERSION: u16 = 1;
pub const NEURAL_INTENT_SIGNED_BYTES: usize = 178;
pub const NEURAL_INTENT_WIRE_BYTES: usize = 210;
pub const NEURAL_REPLAY_WINDOW: usize = 64;
pub const MAX_CHANNELS: u8 = 32;
pub const MAX_SAMPLE_RATE_HZ: u16 = 4_096;

type HmacSha256 = Hmac<Sha256>;

pub fn derive_session_material(pairing_token: &[u8]) -> Result<([u8; 32], [u8; 16]), NeuralError> {
    if pairing_token.len() < 16 {
        return Err(NeuralError::InvalidPairingToken);
    }
    let mut key_hasher = Sha256::new();
    key_hasher.update(b"ferrum-neural-key-v1\0");
    key_hasher.update(pairing_token);
    let key: [u8; 32] = key_hasher.finalize().into();

    let mut session_hasher = Sha256::new();
    session_hasher.update(b"ferrum-neural-session-v1\0");
    session_hasher.update(pairing_token);
    let session_digest: [u8; 32] = session_hasher.finalize().into();
    let mut session_id = [0u8; 16];
    session_id.copy_from_slice(&session_digest[..16]);
    Ok((key, session_id))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum NeuralTransport {
    BrainFlow = 0,
    Lsl = 1,
    Playback = 2,
    Synthetic = 3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum NeuralParadigm {
    Ssvep = 0,
    P300 = 1,
    MotorImagery = 2,
    Eog = 3,
    Emg = 4,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum NeuralClass {
    Cancel = 0,
    FocusLeft = 1,
    FocusRight = 2,
    Select = 3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum SignalQuality {
    Good = 0,
    Degraded = 1,
    Reject = 2,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum NeuralScope {
    Observe = 0,
    Navigate = 1,
    SafeDesktop = 2,
    PhysicalGoal = 3,
}

pub mod artifact_flags {
    pub const BLINK: u16 = 1 << 0;
    pub const MUSCLE: u16 = 1 << 1;
    pub const SATURATION: u16 = 1 << 2;
    pub const CONTACT: u16 = 1 << 3;
    pub const MOTION: u16 = 1 << 4;
    pub const LINE_NOISE: u16 = 1 << 5;
    pub const KNOWN_MASK: u16 = BLINK | MUSCLE | SATURATION | CONTACT | MOTION | LINE_NOISE;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NeuralStreamDescriptorV1 {
    pub session_id: [u8; 16],
    pub source_id: [u8; 16],
    pub board_kind: u16,
    pub transport: NeuralTransport,
    pub sample_rate_hz: u16,
    pub channel_count: u8,
    pub calibration_id: [u8; 32],
    pub sequence_start: u64,
    pub started_monotonic_ns: u64,
}

impl NeuralStreamDescriptorV1 {
    pub fn validate(&self) -> Result<(), NeuralError> {
        if self.session_id == [0; 16] || self.source_id == [0; 16] {
            return Err(NeuralError::ZeroIdentifier);
        }
        if self.calibration_id == [0; 32] {
            return Err(NeuralError::CalibrationMismatch);
        }
        if self.sample_rate_hz == 0 || self.sample_rate_hz > MAX_SAMPLE_RATE_HZ {
            return Err(NeuralError::InvalidSampleRate);
        }
        if self.channel_count == 0 || self.channel_count > MAX_CHANNELS {
            return Err(NeuralError::InvalidChannelCount);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NeuralIntentV1 {
    pub paradigm: NeuralParadigm,
    pub class: NeuralClass,
    pub signal_quality: SignalQuality,
    pub requested_scope: NeuralScope,
    pub artifact_flags: u16,
    pub dwell_windows: u8,
    pub posterior_permille: u16,
    pub margin_permille: u16,
    pub sequence: u64,
    pub window_start_ns: u64,
    pub window_end_ns: u64,
    pub expires_at_ns: u64,
    pub session_id: [u8; 16],
    pub intent_id: [u8; 16],
    pub decoder_version: [u8; 32],
    pub calibration_id: [u8; 32],
    pub subject_key: [u8; 16],
    pub focus_revision: u64,
    pub state_revision: u64,
    pub signature: [u8; 32],
}

impl NeuralIntentV1 {
    pub fn parse(bytes: &[u8]) -> Result<Self, NeuralError> {
        if bytes.len() != NEURAL_INTENT_WIRE_BYTES {
            return Err(NeuralError::InvalidLength);
        }
        if bytes[..4] != NEURAL_INTENT_MAGIC {
            return Err(NeuralError::InvalidMagic);
        }
        if read_u16(bytes, 4)? != NEURAL_INTENT_SCHEMA_VERSION {
            return Err(NeuralError::UnsupportedVersion);
        }
        let paradigm = NeuralParadigm::try_from(bytes[6])?;
        let class = NeuralClass::try_from(bytes[7])?;
        let signal_quality = SignalQuality::try_from(bytes[8])?;
        let requested_scope = NeuralScope::try_from(bytes[9])?;
        let artifact_flags = read_u16(bytes, 10)?;
        if artifact_flags & !artifact_flags::KNOWN_MASK != 0 {
            return Err(NeuralError::UnknownArtifactFlag);
        }
        if bytes[13] != 0 {
            return Err(NeuralError::NonZeroReservedField);
        }
        let intent = Self {
            paradigm,
            class,
            signal_quality,
            requested_scope,
            artifact_flags,
            dwell_windows: bytes[12],
            posterior_permille: read_u16(bytes, 14)?,
            margin_permille: read_u16(bytes, 16)?,
            sequence: read_u64(bytes, 18)?,
            window_start_ns: read_u64(bytes, 26)?,
            window_end_ns: read_u64(bytes, 34)?,
            expires_at_ns: read_u64(bytes, 42)?,
            session_id: read_array(bytes, 50)?,
            intent_id: read_array(bytes, 66)?,
            decoder_version: read_array(bytes, 82)?,
            calibration_id: read_array(bytes, 114)?,
            subject_key: read_array(bytes, 146)?,
            focus_revision: read_u64(bytes, 162)?,
            state_revision: read_u64(bytes, 170)?,
            signature: read_array(bytes, NEURAL_INTENT_SIGNED_BYTES)?,
        };
        intent.validate_shape()?;
        Ok(intent)
    }

    pub fn validate_shape(&self) -> Result<(), NeuralError> {
        if self.posterior_permille > 1_000 || self.margin_permille > 1_000 {
            return Err(NeuralError::InvalidProbability);
        }
        if self.session_id == [0; 16]
            || self.intent_id == [0; 16]
            || self.subject_key == [0; 16]
            || self.decoder_version == [0; 32]
            || self.calibration_id == [0; 32]
        {
            return Err(NeuralError::ZeroIdentifier);
        }
        if self.window_start_ns >= self.window_end_ns || self.window_end_ns >= self.expires_at_ns {
            return Err(NeuralError::InvalidTimeWindow);
        }
        Ok(())
    }

    pub fn verify_signature(&self, bytes: &[u8], key: &[u8]) -> Result<(), NeuralError> {
        if key.len() < 16 || bytes.len() != NEURAL_INTENT_WIRE_BYTES {
            return Err(NeuralError::InvalidSignature);
        }
        let mut mac = HmacSha256::new_from_slice(key).map_err(|_| NeuralError::InvalidSignature)?;
        mac.update(&bytes[..NEURAL_INTENT_SIGNED_BYTES]);
        mac.verify_slice(&self.signature)
            .map_err(|_| NeuralError::InvalidSignature)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NeuralSessionState {
    Disconnected,
    ConnectedUncalibrated,
    Calibrating,
    ObserveOnly,
    ArmedSafeUi,
    CandidateIntent,
    Previewed,
    Cooldown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NeuralPolicy {
    pub minimum_posterior_permille: u16,
    pub minimum_margin_permille: u16,
    pub minimum_dwell_windows: u8,
    pub maximum_window_age_ns: u64,
    pub cooldown_ns: u64,
    pub maximum_sequence_gap: u64,
}

impl Default for NeuralPolicy {
    fn default() -> Self {
        Self {
            minimum_posterior_permille: 800,
            minimum_margin_permille: 150,
            minimum_dwell_windows: 3,
            maximum_window_age_ns: 2_000_000_000,
            cooldown_ns: 750_000_000,
            maximum_sequence_gap: 16,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PreviewDisposition {
    SafeUiCandidate,
    PhysicalProposalOnly,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NeuralPreview {
    pub intent_id: [u8; 16],
    pub class: NeuralClass,
    pub scope: NeuralScope,
    pub disposition: PreviewDisposition,
    pub expires_at_ns: u64,
    pub focus_revision: u64,
    pub state_revision: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NeuralSession {
    state: NeuralSessionState,
    descriptor: Option<NeuralStreamDescriptorV1>,
    last_sequence: Option<u64>,
    recent_ids: [[u8; 16]; NEURAL_REPLAY_WINDOW],
    recent_count: usize,
    recent_cursor: usize,
    pending: Option<NeuralPreview>,
    cooldown_until_ns: u64,
    dropped_samples: u64,
}

impl Default for NeuralSession {
    fn default() -> Self {
        Self {
            state: NeuralSessionState::Disconnected,
            descriptor: None,
            last_sequence: None,
            recent_ids: [[0; 16]; NEURAL_REPLAY_WINDOW],
            recent_count: 0,
            recent_cursor: 0,
            pending: None,
            cooldown_until_ns: 0,
            dropped_samples: 0,
        }
    }
}

impl NeuralSession {
    pub const fn state(&self) -> NeuralSessionState {
        self.state
    }
    pub const fn dropped_samples(&self) -> u64 {
        self.dropped_samples
    }
    pub const fn pending(&self) -> Option<NeuralPreview> {
        self.pending
    }

    pub fn connect(&mut self, descriptor: NeuralStreamDescriptorV1) -> Result<(), NeuralError> {
        descriptor.validate()?;
        if self.state != NeuralSessionState::Disconnected {
            return Err(NeuralError::InvalidStateTransition);
        }
        self.descriptor = Some(descriptor);
        self.state = NeuralSessionState::ConnectedUncalibrated;
        Ok(())
    }

    pub fn begin_calibration(&mut self) -> Result<(), NeuralError> {
        if self.state != NeuralSessionState::ConnectedUncalibrated {
            return Err(NeuralError::InvalidStateTransition);
        }
        self.state = NeuralSessionState::Calibrating;
        Ok(())
    }

    pub fn finish_calibration(&mut self, calibration_id: [u8; 32]) -> Result<(), NeuralError> {
        if self.state != NeuralSessionState::Calibrating || calibration_id == [0; 32] {
            return Err(NeuralError::InvalidStateTransition);
        }
        let descriptor = self.descriptor.as_mut().ok_or(NeuralError::NotConnected)?;
        descriptor.calibration_id = calibration_id;
        self.state = NeuralSessionState::ObserveOnly;
        Ok(())
    }

    pub fn arm_safe_ui(&mut self, trusted_non_neural: bool) -> Result<(), NeuralError> {
        if self.state != NeuralSessionState::ObserveOnly || !trusted_non_neural {
            return Err(NeuralError::NonNeuralArmRequired);
        }
        self.state = NeuralSessionState::ArmedSafeUi;
        Ok(())
    }

    pub fn preview(
        &mut self,
        bytes: &[u8],
        key: &[u8],
        now_ns: u64,
        current_focus_revision: u64,
        current_state_revision: u64,
        policy: NeuralPolicy,
    ) -> Result<NeuralPreview, NeuralError> {
        if self.state == NeuralSessionState::Cooldown {
            if now_ns < self.cooldown_until_ns {
                return Err(NeuralError::CooldownActive);
            }
            self.state = NeuralSessionState::ArmedSafeUi;
        }
        if self.state != NeuralSessionState::ArmedSafeUi {
            return Err(NeuralError::NotArmed);
        }
        let intent = match NeuralIntentV1::parse(bytes) {
            Ok(intent) => intent,
            Err(error) => return self.fail_closed(error),
        };
        if let Err(error) = intent.verify_signature(bytes, key) {
            return self.fail_closed(error);
        }
        let descriptor = self.descriptor.ok_or(NeuralError::NotConnected)?;
        if intent.session_id != descriptor.session_id {
            return self.fail_closed(NeuralError::SessionMismatch);
        }
        if intent.calibration_id != descriptor.calibration_id {
            return self.fail_closed(NeuralError::CalibrationMismatch);
        }
        if intent.window_end_ns > now_ns || intent.expires_at_ns <= now_ns {
            return self.fail_closed(NeuralError::ExpiredOrFuture);
        }
        if now_ns.saturating_sub(intent.window_end_ns) > policy.maximum_window_age_ns {
            return self.fail_closed(NeuralError::StaleWindow);
        }
        if self.recent_ids[..self.recent_count].contains(&intent.intent_id) {
            return self.fail_closed(NeuralError::ReplayedIntent);
        }
        if let Some(last) = self.last_sequence {
            if intent.sequence <= last {
                return self.fail_closed(NeuralError::NonMonotonicSequence);
            }
            let gap = intent.sequence - last;
            if gap > policy.maximum_sequence_gap {
                self.dropped_samples = self.dropped_samples.saturating_add(gap - 1);
                return self.fail_closed(NeuralError::SequenceGap);
            }
        }
        if intent.signal_quality != SignalQuality::Good || intent.artifact_flags != 0 {
            return self.fail_closed(NeuralError::RejectedSignal);
        }
        if intent.posterior_permille < policy.minimum_posterior_permille
            || intent.margin_permille < policy.minimum_margin_permille
            || intent.dwell_windows < policy.minimum_dwell_windows
        {
            return self.fail_closed(NeuralError::InsufficientEvidence);
        }
        if intent.focus_revision != current_focus_revision
            || intent.state_revision != current_state_revision
        {
            return self.fail_closed(NeuralError::RevisionMismatch);
        }
        self.last_sequence = Some(intent.sequence);
        self.remember_id(intent.intent_id);
        self.state = NeuralSessionState::CandidateIntent;
        let disposition = if intent.class == NeuralClass::Cancel {
            PreviewDisposition::Cancelled
        } else if intent.requested_scope == NeuralScope::PhysicalGoal {
            PreviewDisposition::PhysicalProposalOnly
        } else {
            PreviewDisposition::SafeUiCandidate
        };
        let preview = NeuralPreview {
            intent_id: intent.intent_id,
            class: intent.class,
            scope: intent.requested_scope,
            disposition,
            expires_at_ns: intent.expires_at_ns,
            focus_revision: intent.focus_revision,
            state_revision: intent.state_revision,
        };
        if disposition == PreviewDisposition::Cancelled {
            self.pending = None;
            self.state = NeuralSessionState::ObserveOnly;
        } else {
            self.pending = Some(preview);
            self.state = NeuralSessionState::Previewed;
        }
        Ok(preview)
    }

    pub fn commit(
        &mut self,
        intent_id: [u8; 16],
        now_ns: u64,
        current_focus_revision: u64,
        current_state_revision: u64,
        policy: NeuralPolicy,
    ) -> Result<NeuralClass, NeuralError> {
        if self.state != NeuralSessionState::Previewed {
            return Err(NeuralError::NoPreview);
        }
        let preview = self.pending.ok_or(NeuralError::NoPreview)?;
        if preview.intent_id != intent_id {
            return self.fail_closed(NeuralError::IntentMismatch);
        }
        if preview.expires_at_ns <= now_ns {
            return self.fail_closed(NeuralError::ExpiredOrFuture);
        }
        if preview.focus_revision != current_focus_revision
            || preview.state_revision != current_state_revision
        {
            return self.fail_closed(NeuralError::RevisionMismatch);
        }
        if preview.disposition == PreviewDisposition::PhysicalProposalOnly {
            return self.fail_closed(NeuralError::PhysicalExecutionForbidden);
        }
        self.pending = None;
        self.cooldown_until_ns = now_ns.saturating_add(policy.cooldown_ns);
        self.state = NeuralSessionState::Cooldown;
        Ok(preview.class)
    }

    pub fn disarm(&mut self) {
        self.pending = None;
        self.cooldown_until_ns = 0;
        self.state = if self.descriptor.is_some() {
            NeuralSessionState::ObserveOnly
        } else {
            NeuralSessionState::Disconnected
        };
    }

    pub fn disconnect(&mut self) {
        *self = Self::default();
    }

    fn remember_id(&mut self, id: [u8; 16]) {
        self.recent_ids[self.recent_cursor] = id;
        self.recent_cursor = (self.recent_cursor + 1) % NEURAL_REPLAY_WINDOW;
        self.recent_count = self
            .recent_count
            .saturating_add(1)
            .min(NEURAL_REPLAY_WINDOW);
    }

    fn fail_closed<T>(&mut self, error: NeuralError) -> Result<T, NeuralError> {
        self.pending = None;
        self.state = if self.descriptor.is_some() {
            NeuralSessionState::ObserveOnly
        } else {
            NeuralSessionState::Disconnected
        };
        Err(error)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NeuralError {
    InvalidLength,
    InvalidMagic,
    UnsupportedVersion,
    UnknownEnum,
    UnknownArtifactFlag,
    InvalidProbability,
    ZeroIdentifier,
    InvalidTimeWindow,
    InvalidSignature,
    InvalidPairingToken,
    NonZeroReservedField,
    InvalidSampleRate,
    InvalidChannelCount,
    InvalidStateTransition,
    NotConnected,
    NotArmed,
    NonNeuralArmRequired,
    SessionMismatch,
    CalibrationMismatch,
    ExpiredOrFuture,
    StaleWindow,
    ReplayedIntent,
    NonMonotonicSequence,
    SequenceGap,
    RejectedSignal,
    InsufficientEvidence,
    RevisionMismatch,
    CooldownActive,
    NoPreview,
    IntentMismatch,
    PhysicalExecutionForbidden,
    Truncated,
}

macro_rules! enum_try_from {
    ($ty:ty, {$($value:expr => $variant:path),+ $(,)?}) => {
        impl TryFrom<u8> for $ty {
            type Error = NeuralError;
            fn try_from(value: u8) -> Result<Self, Self::Error> {
                match value { $($value => Ok($variant),)+ _ => Err(NeuralError::UnknownEnum) }
            }
        }
    };
}

enum_try_from!(NeuralParadigm, {0 => NeuralParadigm::Ssvep, 1 => NeuralParadigm::P300, 2 => NeuralParadigm::MotorImagery, 3 => NeuralParadigm::Eog, 4 => NeuralParadigm::Emg});
enum_try_from!(NeuralClass, {0 => NeuralClass::Cancel, 1 => NeuralClass::FocusLeft, 2 => NeuralClass::FocusRight, 3 => NeuralClass::Select});
enum_try_from!(SignalQuality, {0 => SignalQuality::Good, 1 => SignalQuality::Degraded, 2 => SignalQuality::Reject});
enum_try_from!(NeuralScope, {0 => NeuralScope::Observe, 1 => NeuralScope::Navigate, 2 => NeuralScope::SafeDesktop, 3 => NeuralScope::PhysicalGoal});

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, NeuralError> {
    let value = bytes
        .get(offset..offset + 2)
        .ok_or(NeuralError::Truncated)?;
    Ok(u16::from_le_bytes([value[0], value[1]]))
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, NeuralError> {
    let value = bytes
        .get(offset..offset + 8)
        .ok_or(NeuralError::Truncated)?;
    Ok(u64::from_le_bytes(
        value.try_into().map_err(|_| NeuralError::Truncated)?,
    ))
}

fn read_array<const N: usize>(bytes: &[u8], offset: usize) -> Result<[u8; N], NeuralError> {
    bytes
        .get(offset..offset + N)
        .ok_or(NeuralError::Truncated)?
        .try_into()
        .map_err(|_| NeuralError::Truncated)
}

#[cfg(test)]
mod tests {
    use super::*;

    const KEY: &[u8] = b"0123456789abcdef0123456789abcdef";

    fn descriptor() -> NeuralStreamDescriptorV1 {
        NeuralStreamDescriptorV1 {
            session_id: [1; 16],
            source_id: [2; 16],
            board_kind: 0,
            transport: NeuralTransport::Synthetic,
            sample_rate_hz: 250,
            channel_count: 8,
            calibration_id: [3; 32],
            sequence_start: 0,
            started_monotonic_ns: 1,
        }
    }

    fn wire(
        class: NeuralClass,
        scope: NeuralScope,
        sequence: u64,
        now: u64,
    ) -> [u8; NEURAL_INTENT_WIRE_BYTES] {
        let mut bytes = [0u8; NEURAL_INTENT_WIRE_BYTES];
        bytes[..4].copy_from_slice(&NEURAL_INTENT_MAGIC);
        bytes[4..6].copy_from_slice(&1u16.to_le_bytes());
        bytes[6] = NeuralParadigm::Ssvep as u8;
        bytes[7] = class as u8;
        bytes[8] = SignalQuality::Good as u8;
        bytes[9] = scope as u8;
        bytes[12] = 3;
        bytes[14..16].copy_from_slice(&900u16.to_le_bytes());
        bytes[16..18].copy_from_slice(&300u16.to_le_bytes());
        bytes[18..26].copy_from_slice(&sequence.to_le_bytes());
        bytes[26..34].copy_from_slice(&(now - 200).to_le_bytes());
        bytes[34..42].copy_from_slice(&(now - 100).to_le_bytes());
        bytes[42..50].copy_from_slice(&(now + 1_000).to_le_bytes());
        bytes[50..66].copy_from_slice(&[1; 16]);
        let mut id = [0u8; 16];
        id[..8].copy_from_slice(&sequence.to_le_bytes());
        bytes[66..82].copy_from_slice(&id);
        bytes[82..114].copy_from_slice(&[4; 32]);
        bytes[114..146].copy_from_slice(&[3; 32]);
        bytes[146..162].copy_from_slice(&[5; 16]);
        bytes[162..170].copy_from_slice(&7u64.to_le_bytes());
        bytes[170..178].copy_from_slice(&9u64.to_le_bytes());
        let mut mac = HmacSha256::new_from_slice(KEY).unwrap();
        mac.update(&bytes[..NEURAL_INTENT_SIGNED_BYTES]);
        bytes[NEURAL_INTENT_SIGNED_BYTES..].copy_from_slice(&mac.finalize().into_bytes());
        bytes
    }

    fn armed() -> NeuralSession {
        let mut session = NeuralSession::default();
        session.connect(descriptor()).unwrap();
        session.begin_calibration().unwrap();
        session.finish_calibration([3; 32]).unwrap();
        session.arm_safe_ui(true).unwrap();
        session
    }

    #[test]
    fn valid_safe_ui_intent_previews_then_commits_once() {
        let now = 10_000;
        let bytes = wire(NeuralClass::FocusRight, NeuralScope::Navigate, 1, now);
        let mut session = armed();
        let preview = session
            .preview(&bytes, KEY, now, 7, 9, NeuralPolicy::default())
            .unwrap();
        assert_eq!(preview.disposition, PreviewDisposition::SafeUiCandidate);
        assert_eq!(
            session.commit(preview.intent_id, now + 10, 7, 9, NeuralPolicy::default()),
            Ok(NeuralClass::FocusRight)
        );
        assert_eq!(
            session.commit(preview.intent_id, now + 20, 7, 9, NeuralPolicy::default()),
            Err(NeuralError::NoPreview)
        );
    }

    #[test]
    fn physical_intent_is_proposal_only_and_never_commits() {
        let now = 10_000;
        let bytes = wire(NeuralClass::Select, NeuralScope::PhysicalGoal, 1, now);
        let mut session = armed();
        let preview = session
            .preview(&bytes, KEY, now, 7, 9, NeuralPolicy::default())
            .unwrap();
        assert_eq!(
            preview.disposition,
            PreviewDisposition::PhysicalProposalOnly
        );
        assert_eq!(
            session.commit(preview.intent_id, now + 10, 7, 9, NeuralPolicy::default()),
            Err(NeuralError::PhysicalExecutionForbidden)
        );
        assert_eq!(session.state(), NeuralSessionState::ObserveOnly);
    }

    #[test]
    fn malformed_stale_replayed_and_bad_mac_fail_closed() {
        let now = 10_000;
        assert_eq!(
            NeuralIntentV1::parse(&[0; 10]),
            Err(NeuralError::InvalidLength)
        );
        let mut session = armed();
        let mut bad = wire(NeuralClass::Select, NeuralScope::Navigate, 1, now);
        bad[180] ^= 1;
        assert_eq!(
            session.preview(&bad, KEY, now, 7, 9, NeuralPolicy::default()),
            Err(NeuralError::InvalidSignature)
        );
        assert_eq!(session.state(), NeuralSessionState::ObserveOnly);
        session.arm_safe_ui(true).unwrap();
        let valid = wire(NeuralClass::Select, NeuralScope::Navigate, 1, now);
        let preview = session
            .preview(&valid, KEY, now, 7, 9, NeuralPolicy::default())
            .unwrap();
        session.disarm();
        session.arm_safe_ui(true).unwrap();
        assert_eq!(
            session.preview(&valid, KEY, now, 7, 9, NeuralPolicy::default()),
            Err(NeuralError::ReplayedIntent)
        );
        assert_eq!(
            preview.intent_id,
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        );
    }

    #[test]
    fn malformed_reserved_field_disarms_and_session_derivation_is_stable() {
        let now = 10_000;
        let mut bytes = wire(NeuralClass::Select, NeuralScope::Navigate, 1, now);
        bytes[13] = 1;
        let mut mac = HmacSha256::new_from_slice(KEY).unwrap();
        mac.update(&bytes[..NEURAL_INTENT_SIGNED_BYTES]);
        bytes[NEURAL_INTENT_SIGNED_BYTES..].copy_from_slice(&mac.finalize().into_bytes());
        let mut session = armed();
        assert_eq!(
            session.preview(&bytes, KEY, now, 7, 9, NeuralPolicy::default()),
            Err(NeuralError::NonZeroReservedField)
        );
        assert_eq!(session.state(), NeuralSessionState::ObserveOnly);

        let first = derive_session_material(KEY).unwrap();
        let second = derive_session_material(KEY).unwrap();
        assert_eq!(first, second);
        assert_ne!(first.0, [0; 32]);
        assert_ne!(first.1, [0; 16]);
        assert_eq!(
            derive_session_material(b"too-short"),
            Err(NeuralError::InvalidPairingToken)
        );
    }

    #[test]
    fn cancellation_disarms_without_a_commit() {
        let now = 10_000;
        let bytes = wire(NeuralClass::Cancel, NeuralScope::Navigate, 1, now);
        let mut session = armed();
        let preview = session
            .preview(&bytes, KEY, now, 7, 9, NeuralPolicy::default())
            .unwrap();
        assert_eq!(preview.disposition, PreviewDisposition::Cancelled);
        assert_eq!(session.state(), NeuralSessionState::ObserveOnly);
        assert_eq!(session.pending(), None);
    }

    #[test]
    fn weak_artifacted_or_racy_evidence_abstains() {
        let now = 10_000;
        for mutation in 0..3 {
            let mut bytes = wire(NeuralClass::Select, NeuralScope::Navigate, 1, now);
            match mutation {
                0 => bytes[12] = 1,
                1 => bytes[10] = 1,
                _ => bytes[14..16].copy_from_slice(&500u16.to_le_bytes()),
            }
            let mut mac = HmacSha256::new_from_slice(KEY).unwrap();
            mac.update(&bytes[..NEURAL_INTENT_SIGNED_BYTES]);
            bytes[NEURAL_INTENT_SIGNED_BYTES..].copy_from_slice(&mac.finalize().into_bytes());
            let mut session = armed();
            assert!(matches!(
                session.preview(&bytes, KEY, now, 7, 9, NeuralPolicy::default()),
                Err(NeuralError::RejectedSignal | NeuralError::InsufficientEvidence)
            ));
            assert_eq!(session.state(), NeuralSessionState::ObserveOnly);
        }
        let bytes = wire(NeuralClass::Select, NeuralScope::Navigate, 1, now);
        let mut session = armed();
        assert_eq!(
            session.preview(&bytes, KEY, now, 8, 9, NeuralPolicy::default()),
            Err(NeuralError::RevisionMismatch)
        );
    }
}
