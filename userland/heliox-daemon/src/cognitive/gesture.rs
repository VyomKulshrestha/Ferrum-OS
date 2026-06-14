#![allow(dead_code)]

extern crate alloc;

use alloc::vec;
use alloc::vec::Vec;

// ---------------------------------------------------------------------------
// 1. GestureType enum
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GestureType {
    None = 0,
    Fist = 1,
    OpenPalm = 2,
    Pointing = 3,
    Peace = 4,
    ThreeFingers = 5,
    FourFingers = 6,
    ThumbsUp = 7,
}

pub fn gesture_name(g: GestureType) -> &'static str {
    match g {
        GestureType::None => "None",
        GestureType::Fist => "Fist",
        GestureType::OpenPalm => "OpenPalm",
        GestureType::Pointing => "Pointing",
        GestureType::Peace => "Peace",
        GestureType::ThreeFingers => "ThreeFingers",
        GestureType::FourFingers => "FourFingers",
        GestureType::ThumbsUp => "ThumbsUp",
    }
}

pub fn from_id(id: u8) -> GestureType {
    match id {
        1 => GestureType::Fist,
        2 => GestureType::OpenPalm,
        3 => GestureType::Pointing,
        4 => GestureType::Peace,
        5 => GestureType::ThreeFingers,
        6 => GestureType::FourFingers,
        7 => GestureType::ThumbsUp,
        _ => GestureType::None,
    }
}

// ---------------------------------------------------------------------------
// 2. HandRegion
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy)]
pub struct HandRegion {
    pub x_min: u16,
    pub y_min: u16,
    pub x_max: u16,
    pub y_max: u16,
    pub cx: u16,
    pub cy: u16,
    pub area: u32,
    pub label: u16,
}

// ---------------------------------------------------------------------------
// 3. Stage 1 — YUYV to skin mask (packed bitfield)
// ---------------------------------------------------------------------------

/// Segments skin pixels from a YUYV frame into a packed bitmask.
///
/// YUYV packs two pixels per 4 bytes: [Y0, Cb, Y1, Cr].
/// A pixel is classified as skin when 77 <= Cb <= 127 AND 133 <= Cr <= 173.
/// The output mask stores one bit per pixel (MSB-first), so its length must
/// be at least `(w * h) / 8` bytes.
pub fn skin_segment(yuyv: &[u8], w: u16, h: u16, mask: &mut [u8]) {
    let total_pixels = (w as u32) * (h as u32);
    let mask_len = ((total_pixels + 7) / 8) as usize;

    // Zero the mask
    for b in mask.iter_mut().take(mask_len) {
        *b = 0;
    }

    // Each YUYV macropixel is 4 bytes encoding 2 horizontally adjacent pixels.
    // Both pixels in the pair share the same Cb and Cr values.
    let macropixels = (total_pixels / 2) as usize;
    let mut pixel_idx: u32 = 0;

    for m in 0..macropixels {
        let base = m * 4;
        if base + 3 >= yuyv.len() {
            break;
        }

        let cb = yuyv[base + 1]; // U  (Cb)
        let cr = yuyv[base + 3]; // V  (Cr)

        let is_skin = cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173;

        if is_skin {
            // Pixel 0 of the pair
            let byte0 = (pixel_idx / 8) as usize;
            let bit0 = 7 - (pixel_idx & 7);
            if byte0 < mask_len {
                mask[byte0] |= 1u8 << bit0;
            }

            // Pixel 1 of the pair
            let p1 = pixel_idx + 1;
            let byte1 = (p1 / 8) as usize;
            let bit1 = 7 - (p1 & 7);
            if byte1 < mask_len {
                mask[byte1] |= 1u8 << bit1;
            }
        }

        pixel_idx += 2;
    }
}

// ---------------------------------------------------------------------------
// Helper: read a bit from the packed mask
// ---------------------------------------------------------------------------

#[inline(always)]
fn mask_bit(mask: &[u8], idx: u32) -> bool {
    let byte = (idx / 8) as usize;
    let bit = 7 - (idx & 7);
    if byte < mask.len() {
        (mask[byte] >> bit) & 1 != 0
    } else {
        false
    }
}

// ---------------------------------------------------------------------------
// 4. Stage 2 — Connected Component Labeling (two-pass with union-find)
// ---------------------------------------------------------------------------

const MAX_LABELS: usize = 512;

/// Inline union-find backed by a fixed-size array.
struct UnionFind {
    parent: [u16; MAX_LABELS],
    count: usize,
}

impl UnionFind {
    fn new() -> Self {
        let mut parent = [0u16; MAX_LABELS];
        for (i, p) in parent.iter_mut().enumerate() {
            *p = i as u16;
        }
        UnionFind { parent, count: 1 } // label 0 is background
    }

    fn next_label(&mut self) -> u16 {
        let l = self.count as u16;
        if self.count < MAX_LABELS {
            self.parent[self.count] = l;
            self.count += 1;
        }
        l
    }

    fn find(&mut self, mut x: u16) -> u16 {
        while self.parent[x as usize] != x {
            // path compression (halving)
            let gp = self.parent[self.parent[x as usize] as usize];
            self.parent[x as usize] = gp;
            x = gp;
        }
        x
    }

    fn union(&mut self, a: u16, b: u16) {
        let ra = self.find(a);
        let rb = self.find(b);
        if ra != rb {
            // Attach larger root to smaller root (keeps numbering low)
            if ra < rb {
                self.parent[rb as usize] = ra;
            } else {
                self.parent[ra as usize] = rb;
            }
        }
    }
}

/// Two-pass connected component labeling on the binary skin mask.
/// `labels` must have at least w*h entries. Returns the largest component as
/// a `HandRegion` if its area >= 500 pixels.
pub fn find_hand(mask: &[u8], w: u16, h: u16, labels: &mut [u16]) -> Option<HandRegion> {
    let ww = w as u32;
    let hh = h as u32;
    let total = (ww * hh) as usize;

    // Clear label buffer
    for l in labels.iter_mut().take(total) {
        *l = 0;
    }

    let mut uf = UnionFind::new();

    // --- Pass 1: assign provisional labels ---
    for y in 0..hh {
        for x in 0..ww {
            let idx = y * ww + x;
            if !mask_bit(mask, idx) {
                continue;
            }

            let left = if x > 0 { labels[(idx - 1) as usize] } else { 0 };
            let above = if y > 0 { labels[(idx - ww) as usize] } else { 0 };

            match (left > 0, above > 0) {
                (false, false) => {
                    // New label
                    if uf.count < MAX_LABELS {
                        labels[idx as usize] = uf.next_label();
                    }
                }
                (true, false) => {
                    labels[idx as usize] = left;
                }
                (false, true) => {
                    labels[idx as usize] = above;
                }
                (true, true) => {
                    let min_l = if left < above { left } else { above };
                    labels[idx as usize] = min_l;
                    if left != above {
                        uf.union(left, above);
                    }
                }
            }
        }
    }

    // --- Pass 2: flatten labels ---
    for idx in 0..total {
        let l = labels[idx];
        if l > 0 {
            labels[idx] = uf.find(l);
        }
    }

    // --- Find largest component ---
    let mut area_buf = [0u32; MAX_LABELS];
    for idx in 0..total {
        let l = labels[idx] as usize;
        if l > 0 && l < MAX_LABELS {
            area_buf[l] += 1;
        }
    }

    let mut best_label: u16 = 0;
    let mut best_area: u32 = 0;
    for (i, &a) in area_buf.iter().enumerate().skip(1) {
        if a > best_area {
            best_area = a;
            best_label = i as u16;
        }
    }

    if best_area < 500 {
        return None;
    }

    // --- Compute bounding box and centroid of largest component ---
    let mut x_min: u16 = w;
    let mut y_min: u16 = h;
    let mut x_max: u16 = 0;
    let mut y_max: u16 = 0;
    let mut sum_x: u32 = 0;
    let mut sum_y: u32 = 0;

    for y in 0..hh {
        for x in 0..ww {
            let idx = (y * ww + x) as usize;
            if labels[idx] == best_label {
                let xx = x as u16;
                let yy = y as u16;
                if xx < x_min { x_min = xx; }
                if yy < y_min { y_min = yy; }
                if xx > x_max { x_max = xx; }
                if yy > y_max { y_max = yy; }
                sum_x += x;
                sum_y += y;
            }
        }
    }

    let cx = (sum_x / best_area) as u16;
    let cy = (sum_y / best_area) as u16;

    Some(HandRegion {
        x_min,
        y_min,
        x_max,
        y_max,
        cx,
        cy,
        area: best_area,
        label: best_label,
    })
}

// ---------------------------------------------------------------------------
// 5. Stage 3 — Contour Tracing (Moore boundary tracing)
// ---------------------------------------------------------------------------

/// 8-connected Moore neighbourhood directions (dx, dy), indexed 0..7.
/// Order: N, NE, E, SE, S, SW, W, NW
const MOORE_DX: [i16; 8] = [0, 1, 1, 1, 0, -1, -1, -1];
const MOORE_DY: [i16; 8] = [-1, -1, 0, 1, 1, 1, 0, -1];

const MAX_CONTOUR_RAW: usize = 2000;

/// Trace the outer boundary of the hand region using Moore boundary tracing.
/// Returns a simplified contour (every 4th point).
pub fn trace_contour(
    labels: &[u16],
    w: u16,
    h: u16,
    hand: &HandRegion,
) -> Vec<(i16, i16)> {
    let ww = w as i16;
    let hh = h as i16;
    let target = hand.label;

    // Find start pixel: topmost row of bounding box, leftmost skin pixel
    let mut start_x: i16 = -1;
    let mut start_y: i16 = -1;

    'outer: for y in (hand.y_min as i16)..=(hand.y_max as i16) {
        for x in (hand.x_min as i16)..=(hand.x_max as i16) {
            if x >= 0 && x < ww && y >= 0 && y < hh {
                let idx = (y as u32) * (w as u32) + (x as u32);
                if labels[idx as usize] == target {
                    start_x = x;
                    start_y = y;
                    break 'outer;
                }
            }
        }
    }

    if start_x < 0 {
        return Vec::new();
    }

    let is_target = |px: i16, py: i16| -> bool {
        if px < 0 || py < 0 || px >= ww || py >= hh {
            return false;
        }
        let idx = (py as u32) * (w as u32) + (px as u32);
        labels[idx as usize] == target
    };

    let mut contour_raw: Vec<(i16, i16)> = Vec::new();
    contour_raw.push((start_x, start_y));

    // Start direction: come from the west (direction index 6 = W), so the
    // first backtrack direction is W (we entered from the left).
    let mut cx = start_x;
    let mut cy = start_y;
    // The direction we came FROM. We start scanning from (backtrack + 1) mod 8.
    let mut backtrack_dir: usize = 6; // came from west

    for _ in 0..MAX_CONTOUR_RAW {
        // Scan the 8 neighbours starting from (backtrack_dir + 1) % 8
        // going clockwise (increasing direction index mod 8)... 
        // Actually Moore tracing scans COUNTER-clockwise from the backtrack.
        // Standard Moore: scan clockwise starting from the pixel we came from.
        let scan_start = (backtrack_dir + 1) % 8;
        let mut found = false;

        for k in 0..8 {
            let dir = (scan_start + k) % 8;
            let nx = cx + MOORE_DX[dir];
            let ny = cy + MOORE_DY[dir];

            if is_target(nx, ny) {
                cx = nx;
                cy = ny;
                // Backtrack direction: opposite of direction we moved
                backtrack_dir = (dir + 4) % 8;
                contour_raw.push((cx, cy));
                found = true;
                break;
            }
        }

        if !found {
            break; // isolated pixel
        }

        // Check if we returned to start
        if cx == start_x && cy == start_y {
            break;
        }
    }

    // Simplify: keep every 4th point
    let mut simplified: Vec<(i16, i16)> = Vec::new();
    for (i, &pt) in contour_raw.iter().enumerate() {
        if i % 4 == 0 {
            simplified.push(pt);
        }
    }

    // Ensure we have at least a few points
    if simplified.len() < 3 && contour_raw.len() >= 3 {
        return contour_raw;
    }

    simplified
}

// ---------------------------------------------------------------------------
// 6. Stage 4 — Convex Hull (Graham scan) + Convexity Defects
// ---------------------------------------------------------------------------

/// Integer cross product: (b - a) × (c - a)
#[inline]
fn cross(a: (i16, i16), b: (i16, i16), c: (i16, i16)) -> i32 {
    let bax = (b.0 as i32) - (a.0 as i32);
    let bay = (b.1 as i32) - (a.1 as i32);
    let cax = (c.0 as i32) - (a.0 as i32);
    let cay = (c.1 as i32) - (a.1 as i32);
    bax * cay - bay * cax
}

/// Squared distance between two points.
#[inline]
fn dist_sq(a: (i16, i16), b: (i16, i16)) -> i32 {
    let dx = (a.0 as i32) - (b.0 as i32);
    let dy = (a.1 as i32) - (b.1 as i32);
    dx * dx + dy * dy
}

/// Graham scan convex hull. Returns indices into `pts` forming the hull in
/// counter-clockwise order.
fn convex_hull_indices(pts: &[(i16, i16)]) -> Vec<usize> {
    let n = pts.len();
    if n < 3 {
        let mut v = Vec::new();
        for i in 0..n {
            v.push(i);
        }
        return v;
    }

    // Find the bottom-most (then left-most) point
    let mut pivot = 0usize;
    for i in 1..n {
        if pts[i].1 > pts[pivot].1 || (pts[i].1 == pts[pivot].1 && pts[i].0 < pts[pivot].0) {
            pivot = i;
        }
    }

    // Build index array sorted by polar angle around pivot
    let mut order: Vec<usize> = Vec::with_capacity(n);
    for i in 0..n {
        order.push(i);
    }

    // Swap pivot to front
    order.swap(0, pivot);

    let pv = pts[order[0]];

    // Sort indices 1..n by polar angle using insertion sort (no alloc-heavy sort)
    // For the sizes we expect (~60-100 points) insertion sort is fine.
    for i in 2..n {
        let mut j = i;
        while j > 1 {
            let a = pts[order[j]];
            let b = pts[order[j - 1]];
            let c = cross(pv, b, a);
            if c > 0 || (c == 0 && dist_sq(pv, a) < dist_sq(pv, b)) {
                order.swap(j, j - 1);
                j -= 1;
            } else {
                break;
            }
        }
    }

    // Graham scan
    let mut stack: Vec<usize> = Vec::with_capacity(n);
    stack.push(order[0]);
    stack.push(order[1]);

    for i in 2..n {
        while stack.len() > 1 {
            let top = stack.len() - 1;
            let c = cross(pts[stack[top - 1]], pts[stack[top]], pts[order[i]]);
            if c <= 0 {
                stack.pop();
            } else {
                break;
            }
        }
        stack.push(order[i]);
    }

    stack
}

/// Squared distance from point `p` to line segment `a`–`b`, multiplied by
/// the squared length of the segment (to stay in integer domain).
///
/// Returns `(numerator, denominator)` where the true squared distance is
/// `numerator / denominator`. We compare `numerator` against
/// `threshold * denominator` to avoid division.
#[inline]
fn point_to_segment_dist_sq_parts(
    p: (i16, i16),
    a: (i16, i16),
    b: (i16, i16),
) -> (i64, i64) {
    let abx = (b.0 as i64) - (a.0 as i64);
    let aby = (b.1 as i64) - (a.1 as i64);
    let apx = (p.0 as i64) - (a.0 as i64);
    let apy = (p.1 as i64) - (a.1 as i64);

    let seg_len_sq = abx * abx + aby * aby;
    if seg_len_sq == 0 {
        let d = apx * apx + apy * apy;
        return (d, 1);
    }

    // Cross product gives area of parallelogram; squared / seg_len_sq = dist²
    let cross_val = apx * aby - apy * abx;
    let num = cross_val * cross_val; // always >= 0

    (num, seg_len_sq)
}

/// Depth threshold squared (≈20 pixels depth → 400).
const DEFECT_DEPTH_SQ_THRESH: i64 = 400;

/// Count convexity defects that exceed the depth threshold.
fn count_deep_defects(contour: &[(i16, i16)], hull_indices: &[usize]) -> u32 {
    let hull_len = hull_indices.len();
    if hull_len < 3 || contour.is_empty() {
        return 0;
    }

    let n = contour.len();
    let mut defect_count: u32 = 0;

    for hi in 0..hull_len {
        let hi_next = (hi + 1) % hull_len;

        let start_idx = hull_indices[hi];
        let end_idx = hull_indices[hi_next];

        let a = contour[start_idx];
        let b = contour[end_idx];

        // Walk contour points between start_idx and end_idx
        let mut max_num: i64 = 0;
        let mut max_den: i64 = 1;

        let mut ci = (start_idx + 1) % n;
        while ci != end_idx {
            let p = contour[ci];
            let (num, den) = point_to_segment_dist_sq_parts(p, a, b);
            // Compare num/den > max_num/max_den  →  num * max_den > max_num * den
            if num * max_den > max_num * den {
                max_num = num;
                max_den = den;
            }
            ci = (ci + 1) % n;
        }

        // Check if deepest point exceeds threshold:
        // max_num / max_den > DEFECT_DEPTH_SQ_THRESH
        // ⇒ max_num > DEFECT_DEPTH_SQ_THRESH * max_den
        if max_num > DEFECT_DEPTH_SQ_THRESH * max_den {
            defect_count += 1;
        }
    }

    defect_count
}

// ---------------------------------------------------------------------------
// 7. Gesture classification from contour + hand region
// ---------------------------------------------------------------------------

pub fn classify_gesture(contour: &[(i16, i16)], hand: &HandRegion) -> GestureType {
    if contour.len() < 5 {
        return GestureType::None;
    }

    let hull_indices = convex_hull_indices(contour);
    let defects = count_deep_defects(contour, &hull_indices);

    let bbox_w = (hand.x_max - hand.x_min + 1) as u32;
    let bbox_h = (hand.y_max - hand.y_min + 1) as u32;

    match defects {
        0 => {
            // Check compactness: area ratio = area * 100 / (bbox_w * bbox_h)
            let bbox_area = bbox_w * bbox_h;
            if bbox_area == 0 {
                return GestureType::Fist;
            }
            let _ratio = (hand.area * 100) / bbox_area;
            // Compact or not, 0 defects → Fist
            GestureType::Fist
        }
        1 => {
            // Elongated: height*100/width > 180
            if bbox_w == 0 {
                return GestureType::Pointing;
            }
            let elongation = (bbox_h * 100) / bbox_w;
            if elongation > 180 {
                GestureType::Pointing
            } else {
                GestureType::Peace
            }
        }
        2 => GestureType::ThreeFingers,
        3 => GestureType::FourFingers,
        _ => GestureType::OpenPalm, // 4+
    }
}

// ---------------------------------------------------------------------------
// 8. Temporal Smoothing — GestureTracker
// ---------------------------------------------------------------------------

pub struct GestureTracker {
    history: [GestureType; 3],
    head: usize,
    last_emitted: GestureType,
}

impl GestureTracker {
    pub fn new() -> Self {
        GestureTracker {
            history: [GestureType::None; 3],
            head: 0,
            last_emitted: GestureType::None,
        }
    }

    pub fn push(&mut self, g: GestureType) {
        self.history[self.head] = g;
        self.head = (self.head + 1) % 3;
    }

    /// Returns `Some(gesture)` only when all three history slots agree AND the
    /// gesture differs from the last emitted one.
    pub fn stable_gesture(&mut self) -> Option<GestureType> {
        let a = self.history[0];
        let b = self.history[1];
        let c = self.history[2];

        if a == b && b == c && a != self.last_emitted {
            self.last_emitted = a;
            Some(a)
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// 9. Top-level API
// ---------------------------------------------------------------------------

/// Process a single YUYV camera frame and return the detected gesture.
///
/// * `yuyv`   — raw YUYV frame data (w*h*2 bytes)
/// * `w`, `h` — frame dimensions (expected 320×240)
/// * `labels` — scratch buffer, must be at least w*h entries
/// * `mask`   — scratch buffer, must be at least w*h/8 bytes
pub fn process_frame(
    yuyv: &[u8],
    w: u16,
    h: u16,
    labels: &mut [u16],
    mask: &mut [u8],
) -> GestureType {
    // Stage 1: Skin segmentation
    skin_segment(yuyv, w, h, mask);

    // Stage 2: Connected component labeling → find hand
    let hand = match find_hand(mask, w, h, labels) {
        Some(hr) => hr,
        None => return GestureType::None,
    };

    // Stage 3: Contour tracing
    let contour = trace_contour(labels, w, h, &hand);
    if contour.len() < 5 {
        return GestureType::None;
    }

    // Stage 4+5: Classify gesture from contour + hull defects
    classify_gesture(&contour, &hand)
}
