//! Capability-contained neural intent service.
//!
//! Only signed, expiring intent evidence enters this boundary. Raw EEG stays
//! in host `neurod`; physical scope remains preview-only by construction.

use alloc::format;
use alloc::string::String;

use ferrum_neural_protocol::{
    derive_session_material, NeuralClass, NeuralError, NeuralPolicy, NeuralPreview,
    NeuralScope, NeuralSession, NeuralSessionState, NeuralStreamDescriptorV1,
    NeuralTransport, PreviewDisposition, NEURAL_INTENT_WIRE_BYTES,
};

const SAFE_TARGETS: [&str; 3] = ["system_info", "list_processes", "physical_status"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NeuralCommit {
    FocusChanged,
    ReadOnlyTool(&'static str),
}

#[derive(Debug)]
pub struct NeuralService {
    session: NeuralSession,
    session_key: Option<[u8; 32]>,
    session_id: Option<[u8; 16]>,
    control_mode: &'static str,
    focus_index: usize,
    focus_revision: u64,
    state_revision: u64,
    accepted_intents: u64,
    rejected_intents: u64,
    committed_intents: u64,
    disarm_count: u64,
    last_error: Option<NeuralError>,
}

impl Default for NeuralService {
    fn default() -> Self {
        Self {
            session: NeuralSession::default(),
            session_key: None,
            session_id: None,
            control_mode: "none",
            focus_index: 0,
            focus_revision: 0,
            state_revision: 0,
            accepted_intents: 0,
            rejected_intents: 0,
            committed_intents: 0,
            disarm_count: 0,
            last_error: None,
        }
    }
}

impl NeuralService {
    pub fn pair(&mut self, pairing_token: &[u8], control_mode: &str) -> Result<(), NeuralError> {
        let (key, session_id) = derive_session_material(pairing_token)?;
        self.session.disconnect();
        self.session_key = Some(key);
        self.session_id = Some(session_id);
        self.control_mode = if control_mode == "cooperative" {
            "cooperative"
        } else {
            "exclusive"
        };
        self.state_revision = self.state_revision.saturating_add(1);
        self.last_error = None;
        Ok(())
    }

    pub fn set_control_mode(&mut self, control_mode: &str) {
        self.control_mode = if control_mode == "cooperative" {
            "cooperative"
        } else {
            "exclusive"
        };
        self.state_revision = self.state_revision.saturating_add(1);
        self.disarm();
    }

    pub fn calibrate(
        &mut self,
        transport: NeuralTransport,
        sample_rate_hz: u16,
        channel_count: u8,
        calibration_id: [u8; 32],
        now_ns: u64,
    ) -> Result<(), NeuralError> {
        let session_id = self.session_id.ok_or(NeuralError::NotConnected)?;
        self.session.disconnect();
        let mut source_id = session_id;
        for byte in &mut source_id {
            *byte ^= 0xa5;
        }
        let descriptor = NeuralStreamDescriptorV1 {
            session_id,
            source_id,
            board_kind: 0,
            transport,
            sample_rate_hz,
            channel_count,
            calibration_id,
            sequence_start: 0,
            started_monotonic_ns: now_ns,
        };
        self.session.connect(descriptor)?;
        self.session.begin_calibration()?;
        self.session.finish_calibration(calibration_id)?;
        self.state_revision = self.state_revision.saturating_add(1);
        self.last_error = None;
        Ok(())
    }

    pub fn arm_from_non_neural_input(&mut self) -> Result<(), NeuralError> {
        self.session.arm_safe_ui(true)?;
        self.state_revision = self.state_revision.saturating_add(1);
        self.last_error = None;
        Ok(())
    }

    pub fn disarm(&mut self) {
        self.session.disarm();
        self.disarm_count = self.disarm_count.saturating_add(1);
        self.state_revision = self.state_revision.saturating_add(1);
    }

    pub fn disconnect(&mut self) {
        self.session.disconnect();
        self.session_key = None;
        self.session_id = None;
        self.control_mode = "none";
        self.disarm_count = self.disarm_count.saturating_add(1);
        self.state_revision = self.state_revision.saturating_add(1);
    }

    pub fn preview(
        &mut self,
        wire: &[u8; NEURAL_INTENT_WIRE_BYTES],
        now_ns: u64,
    ) -> Result<NeuralPreview, NeuralError> {
        let key = self.session_key.ok_or(NeuralError::NotConnected)?;
        match self.session.preview(
            wire,
            &key,
            now_ns,
            self.focus_revision,
            self.state_revision,
            NeuralPolicy::default(),
        ) {
            Ok(preview) => {
                self.accepted_intents = self.accepted_intents.saturating_add(1);
                self.last_error = None;
                Ok(preview)
            }
            Err(error) => {
                self.rejected_intents = self.rejected_intents.saturating_add(1);
                self.last_error = Some(error);
                Err(error)
            }
        }
    }

    pub fn commit(
        &mut self,
        intent_id: [u8; 16],
        now_ns: u64,
    ) -> Result<NeuralCommit, NeuralError> {
        let class = self.session.commit(
            intent_id,
            now_ns,
            self.focus_revision,
            self.state_revision,
            NeuralPolicy::default(),
        )?;
        let result = match class {
            NeuralClass::FocusLeft => {
                self.focus_index = if self.focus_index == 0 {
                    SAFE_TARGETS.len() - 1
                } else {
                    self.focus_index - 1
                };
                self.focus_revision = self.focus_revision.saturating_add(1);
                NeuralCommit::FocusChanged
            }
            NeuralClass::FocusRight => {
                self.focus_index = (self.focus_index + 1) % SAFE_TARGETS.len();
                self.focus_revision = self.focus_revision.saturating_add(1);
                NeuralCommit::FocusChanged
            }
            NeuralClass::Select => NeuralCommit::ReadOnlyTool(SAFE_TARGETS[self.focus_index]),
            NeuralClass::Cancel => return Err(NeuralError::NoPreview),
        };
        self.committed_intents = self.committed_intents.saturating_add(1);
        self.last_error = None;
        Ok(result)
    }

    pub fn status_json(&self, now_ns: u64) -> String {
        let session_id = self
            .session_id
            .map(|id| hex(&id))
            .unwrap_or_else(|| String::from(""));
        let pending = self.session.pending();
        let pending_json = match pending {
            Some(preview) => format!(
                "{{\"intent_id\":\"{}\",\"class\":\"{}\",\"scope\":\"{}\",\"disposition\":\"{}\"}}",
                hex(&preview.intent_id),
                class_name(preview.class),
                scope_name(preview.scope),
                disposition_name(preview.disposition),
            ),
            None => String::from("null"),
        };
        let last_error = self
            .last_error
            .map(error_name)
            .unwrap_or("none");
        format!(
            "{{\"schema_version\":1,\"raw_eeg_in_os\":false,\"state\":\"{}\",\"paired\":{},\"session_id\":\"{}\",\"control_mode\":\"{}\",\"monotonic_ns\":{},\"focus_index\":{},\"focus_target\":\"{}\",\"focus_revision\":{},\"state_revision\":{},\"pending\":{},\"accepted_intents\":{},\"rejected_intents\":{},\"committed_intents\":{},\"disarm_count\":{},\"dropped_samples\":{},\"last_error\":\"{}\",\"physical_scope\":\"proposal_only\"}}",
            state_name(self.session.state()),
            self.session_key.is_some(),
            session_id,
            self.control_mode,
            now_ns,
            self.focus_index,
            SAFE_TARGETS[self.focus_index],
            self.focus_revision,
            self.state_revision,
            pending_json,
            self.accepted_intents,
            self.rejected_intents,
            self.committed_intents,
            self.disarm_count,
            self.session.dropped_samples(),
            last_error,
        )
    }
}

pub fn transport_from_name(name: &str) -> Result<NeuralTransport, NeuralError> {
    match name {
        "brainflow" => Ok(NeuralTransport::BrainFlow),
        "lsl" => Ok(NeuralTransport::Lsl),
        "playback" => Ok(NeuralTransport::Playback),
        "synthetic" => Ok(NeuralTransport::Synthetic),
        _ => Err(NeuralError::InvalidStateTransition),
    }
}

pub fn preview_json(preview: NeuralPreview) -> String {
    format!(
        "{{\"intent_id\":\"{}\",\"class\":\"{}\",\"scope\":\"{}\",\"disposition\":\"{}\",\"executable\":{},\"expires_at_ns\":{}}}",
        hex(&preview.intent_id),
        class_name(preview.class),
        scope_name(preview.scope),
        disposition_name(preview.disposition),
        preview.disposition == PreviewDisposition::SafeUiCandidate,
        preview.expires_at_ns,
    )
}

pub fn error_name(error: NeuralError) -> &'static str {
    match error {
        NeuralError::InvalidLength => "invalid_length",
        NeuralError::InvalidMagic => "invalid_magic",
        NeuralError::UnsupportedVersion => "unsupported_version",
        NeuralError::UnknownEnum => "unknown_enum",
        NeuralError::UnknownArtifactFlag => "unknown_artifact_flag",
        NeuralError::InvalidProbability => "invalid_probability",
        NeuralError::ZeroIdentifier => "zero_identifier",
        NeuralError::InvalidTimeWindow => "invalid_time_window",
        NeuralError::InvalidSignature => "invalid_signature",
        NeuralError::InvalidPairingToken => "invalid_pairing_token",
        NeuralError::NonZeroReservedField => "nonzero_reserved_field",
        NeuralError::InvalidSampleRate => "invalid_sample_rate",
        NeuralError::InvalidChannelCount => "invalid_channel_count",
        NeuralError::InvalidStateTransition => "invalid_state_transition",
        NeuralError::NotConnected => "not_connected",
        NeuralError::NotArmed => "not_armed",
        NeuralError::NonNeuralArmRequired => "non_neural_arm_required",
        NeuralError::SessionMismatch => "session_mismatch",
        NeuralError::CalibrationMismatch => "calibration_mismatch",
        NeuralError::ExpiredOrFuture => "expired_or_future",
        NeuralError::StaleWindow => "stale_window",
        NeuralError::ReplayedIntent => "replayed_intent",
        NeuralError::NonMonotonicSequence => "non_monotonic_sequence",
        NeuralError::SequenceGap => "sequence_gap",
        NeuralError::RejectedSignal => "rejected_signal",
        NeuralError::InsufficientEvidence => "insufficient_evidence",
        NeuralError::RevisionMismatch => "revision_mismatch",
        NeuralError::CooldownActive => "cooldown_active",
        NeuralError::NoPreview => "no_preview",
        NeuralError::IntentMismatch => "intent_mismatch",
        NeuralError::PhysicalExecutionForbidden => "physical_execution_forbidden",
        NeuralError::Truncated => "truncated",
    }
}

fn state_name(state: NeuralSessionState) -> &'static str {
    match state {
        NeuralSessionState::Disconnected => "disconnected",
        NeuralSessionState::ConnectedUncalibrated => "connected_uncalibrated",
        NeuralSessionState::Calibrating => "calibrating",
        NeuralSessionState::ObserveOnly => "observe_only",
        NeuralSessionState::ArmedSafeUi => "armed_safe_ui",
        NeuralSessionState::CandidateIntent => "candidate_intent",
        NeuralSessionState::Previewed => "previewed",
        NeuralSessionState::Cooldown => "cooldown",
    }
}

fn class_name(class: NeuralClass) -> &'static str {
    match class {
        NeuralClass::Cancel => "cancel",
        NeuralClass::FocusLeft => "focus_left",
        NeuralClass::FocusRight => "focus_right",
        NeuralClass::Select => "select",
    }
}

fn scope_name(scope: NeuralScope) -> &'static str {
    match scope {
        NeuralScope::Observe => "observe",
        NeuralScope::Navigate => "navigate",
        NeuralScope::SafeDesktop => "safe_desktop",
        NeuralScope::PhysicalGoal => "physical_goal",
    }
}

fn disposition_name(disposition: PreviewDisposition) -> &'static str {
    match disposition {
        PreviewDisposition::SafeUiCandidate => "safe_ui_candidate",
        PreviewDisposition::PhysicalProposalOnly => "physical_proposal_only",
        PreviewDisposition::Cancelled => "cancelled",
    }
}

fn hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push_str(&format!("{:02x}", byte));
    }
    output
}
