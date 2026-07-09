// ============================================================================
// FerrumOS - Multi-User Accounts
// ============================================================================
// A real user account registry, persisted to disk (/disk/accounts.txt,
// one colon-separated record per line - uid:username:profile:home,
// deliberately the same shape as a classic /etc/passwd line). `login`
// (src/shell/commands.rs) switches the active shell session to an
// account here, which resolves to a real capability set
// (`capabilities_for_profile`) - a logged-in non-root user genuinely
// cannot do what root can, not just a cosmetic username change.
// ============================================================================

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;

const ACCOUNTS_PATH: &str = "/disk/accounts.txt";
const HOME_ROOT: &str = "/disk/home";
const FIRST_USER_UID: u32 = 1000;

#[derive(Debug, Clone, PartialEq)]
pub struct Account {
    pub uid: u32,
    pub username: String,
    /// One of "root", "user", "guest" - see `capabilities_for_profile`.
    pub profile: String,
    pub home: String,
}

fn seed_accounts() -> Vec<Account> {
    alloc::vec![Account {
        uid: 0,
        username: String::from("root"),
        profile: String::from("root"),
        home: String::from("/disk/root"),
    }]
}

fn parse_line(line: &str) -> Option<Account> {
    let mut parts = line.splitn(4, ':');
    let uid = parts.next()?.parse::<u32>().ok()?;
    let username = parts.next()?.to_string();
    let profile = parts.next()?.to_string();
    let home = parts.next()?.to_string();
    Some(Account { uid, username, profile, home })
}

fn format_line(a: &Account) -> String {
    format!("{}:{}:{}:{}", a.uid, a.username, a.profile, a.home)
}

pub fn list() -> Vec<Account> {
    match crate::fs::read_file(ACCOUNTS_PATH) {
        Ok(content) => {
            let accounts: Vec<Account> = content.lines().filter_map(parse_line).collect();
            if accounts.is_empty() { seed_accounts() } else { accounts }
        }
        Err(_) => seed_accounts(),
    }
}

fn write_accounts(accounts: &[Account]) -> Result<(), String> {
    let content = accounts.iter().map(format_line).collect::<Vec<_>>().join("\n");
    let _ = crate::fs::remove(ACCOUNTS_PATH);
    crate::fs::create_file(ACCOUNTS_PATH, &content)
}

pub fn find(username: &str) -> Option<Account> {
    list().into_iter().find(|a| a.username == username)
}

/// Capabilities granted to each account profile. "user" is deliberately
/// a real, usable middle ground - not just root-or-nothing: it can spawn
/// processes, open GUI windows, read/write its own files, and reach the
/// network, but holds none of root's admin-only tokens (no quota
/// exemption, no confirmation-gate bypass, no kexec, no killing other
/// users' processes).
pub fn capabilities_for_profile(profile: &str) -> Vec<String> {
    match profile {
        "root" => alloc::vec![String::from("cap:system:all")],
        "user" => alloc::vec![
            String::from("cap:fs:read"),
            String::from("cap:fs:write"),
            String::from("cap:process:spawn"),
            String::from("cap:gui:window"),
            String::from("cap:ipc:send"),
            String::from("cap:net:connect"),
            String::from("cap:audio:play"),
            String::from("cap:camera:read"),
        ],
        _ => alloc::vec![String::from("cap:fs:read")], // "guest" and anything unrecognized
    }
}

pub fn create(username: &str, profile: &str) -> Result<Account, String> {
    if username.is_empty() || !username.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err(String::from("username must be alphanumeric/underscore only"));
    }
    if !["root", "user", "guest"].contains(&profile) {
        return Err(format!("unknown profile '{}' (expected root, user, or guest)", profile));
    }
    let mut accounts = list();
    if accounts.iter().any(|a| a.username == username) {
        return Err(format!("account already exists: {}", username));
    }
    let uid = if profile == "root" {
        0
    } else {
        accounts.iter().map(|a| a.uid).max().unwrap_or(FIRST_USER_UID - 1).max(FIRST_USER_UID - 1) + 1
    };
    let home = format!("{}/{}", HOME_ROOT, username);

    // Best-effort home directory creation - the account is still real
    // and usable even on RamFS-only boots without /disk/home pre-created,
    // it just won't have a persisted home directory to write into yet.
    let _ = crate::fs::create_dir(HOME_ROOT);
    let _ = crate::fs::create_dir(&home);

    let account = Account { uid, username: username.to_string(), profile: profile.to_string(), home };
    accounts.push(account.clone());
    write_accounts(&accounts)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::CapabilityGranted,
        &format!("accounts: created user '{}' (uid={}, profile={})", username, uid, profile),
    );
    Ok(account)
}
