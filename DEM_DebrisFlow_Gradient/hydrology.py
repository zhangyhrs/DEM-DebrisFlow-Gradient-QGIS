# -*- coding: utf-8 -*-
import heapq
import math
from collections import deque

import numpy as np

# D8 邻域，顺序不影响计算，仅用于遍历
D8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def priority_flood_fill(dem, mask):
    """Priority-Flood 洼地填充。dem 为二维 float 数组；mask=True 表示参与计算。"""
    rows, cols = dem.shape
    filled = dem.astype(np.float64, copy=True)
    visited = np.zeros((rows, cols), dtype=bool)
    pq = []

    def is_boundary(r, c):
        if not mask[r, c]:
            return False
        if r == 0 or c == 0 or r == rows - 1 or c == cols - 1:
            return True
        for dr, dc in D8:
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= rows or cc < 0 or cc >= cols or not mask[rr, cc]:
                return True
        return False

    for r in range(rows):
        for c in range(cols):
            if is_boundary(r, c):
                visited[r, c] = True
                heapq.heappush(pq, (filled[r, c], r, c))

    # 极端情况下（mask 无边界）
    if not pq:
        inds = np.argwhere(mask)
        if len(inds) == 0:
            return filled
        r, c = inds[0]
        visited[r, c] = True
        heapq.heappush(pq, (filled[r, c], int(r), int(c)))

    while pq:
        elev, r, c = heapq.heappop(pq)
        for dr, dc in D8:
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                continue
            if not mask[rr, cc] or visited[rr, cc]:
                continue
            visited[rr, cc] = True
            ne = filled[rr, cc]
            if ne < elev:
                ne = elev
                filled[rr, cc] = ne
            heapq.heappush(pq, (ne, rr, cc))

    return filled


def d8_flow_direction(filled, mask, pixel_x, pixel_y):
    """返回下游像元线性索引；-1 表示无下游。允许边界像元无下游。"""
    rows, cols = filled.shape
    downstream = np.full(rows * cols, -1, dtype=np.int64)

    dx = abs(float(pixel_x))
    dy = abs(float(pixel_y))

    for r in range(rows):
        for c in range(cols):
            if not mask[r, c]:
                continue
            z = filled[r, c]
            best_slope = 0.0
            best = -1
            for dr, dc in D8:
                rr, cc = r + dr, c + dc
                if rr < 0 or rr >= rows or cc < 0 or cc >= cols or not mask[rr, cc]:
                    continue
                dz = z - filled[rr, cc]
                if dz <= 0:
                    continue
                dist = math.hypot(dc * dx, dr * dy)
                if dist <= 0:
                    continue
                slope = dz / dist
                if slope > best_slope:
                    best_slope = slope
                    best = rr * cols + cc
            downstream[r * cols + c] = best

    return downstream


def flow_accumulation(downstream, mask):
    """D8 汇流累积量，单位为像元数，包含本像元。"""
    rows, cols = mask.shape
    n = rows * cols
    indeg = np.zeros(n, dtype=np.int32)
    acc = np.zeros(n, dtype=np.float64)
    valid = mask.reshape(-1)
    acc[valid] = 1.0

    valid_idx = np.flatnonzero(valid)
    for i in valid_idx:
        j = downstream[i]
        if j >= 0:
            indeg[j] += 1

    q = deque(int(i) for i in valid_idx if indeg[i] == 0)
    processed = 0
    while q:
        i = q.popleft()
        processed += 1
        j = downstream[i]
        if j >= 0:
            acc[j] += acc[i]
            indeg[j] -= 1
            if indeg[j] == 0:
                q.append(int(j))

    # 若存在平台造成的未处理像元，仍保留当前累积值，不中断任务
    return acc.reshape((rows, cols))


def upstream_lists(downstream, mask):
    rows, cols = mask.shape
    ups = [[] for _ in range(rows * cols)]
    for i in np.flatnonzero(mask.reshape(-1)):
        j = downstream[i]
        if j >= 0:
            ups[j].append(int(i))
    return ups


def boundary_cells(mask):
    rows, cols = mask.shape
    out = []
    for r in range(rows):
        for c in range(cols):
            if not mask[r, c]:
                continue
            if r == 0 or c == 0 or r == rows - 1 or c == cols - 1:
                out.append((r, c))
                continue
            for dr, dc in D8:
                rr, cc = r + dr, c + dc
                if rr < 0 or rr >= rows or cc < 0 or cc >= cols or not mask[rr, cc]:
                    out.append((r, c))
                    break
    return out


def choose_outlet(mask, acc, filled):
    """优先选流域边界上汇流累积量最大的像元；并以较低高程作为并列时优先。"""
    bcs = boundary_cells(mask)
    if not bcs:
        inds = np.argwhere(mask)
        if len(inds) == 0:
            return None
        vals = [(acc[r, c], -filled[r, c], int(r), int(c)) for r, c in inds]
        _, _, r, c = max(vals)
        return r, c
    return max(bcs, key=lambda rc: (acc[rc[0], rc[1]], -filled[rc[0], rc[1]]))


def trace_main_channel(mask, downstream, acc, outlet_rc, min_acc_cells=1.0):
    """从沟口沿上游最大汇流路径反向追踪主沟道。返回 [(r,c), ...]，顺序为沟口->沟顶。"""
    if outlet_rc is None:
        return []
    rows, cols = mask.shape
    ups = upstream_lists(downstream, mask)
    r, c = outlet_rc
    cur = r * cols + c
    path = [cur]
    seen = {cur}

    while True:
        candidates = [u for u in ups[cur] if acc.reshape(-1)[u] >= min_acc_cells]
        if not candidates:
            # 为了追踪至源头，若阈值导致无候选，则继续选所有上游中累积量最大的一个
            candidates = ups[cur]
        if not candidates:
            break
        nxt = max(candidates, key=lambda u: acc.reshape(-1)[u])
        if nxt in seen:
            break
        seen.add(nxt)
        path.append(nxt)
        cur = nxt

    return [(i // cols, i % cols) for i in path]


def snap_outlet_to_max_acc(point_rc, acc, mask, radius_cells=5):
    """将沟口点吸附到指定半径内汇流累积量最大的有效像元。"""
    if point_rc is None:
        return None
    rows, cols = mask.shape
    pr, pc = point_rc
    best = None
    r0 = max(0, pr - int(radius_cells))
    r1 = min(rows - 1, pr + int(radius_cells))
    c0 = max(0, pc - int(radius_cells))
    c1 = min(cols - 1, pc + int(radius_cells))
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            if not mask[r, c]:
                continue
            d2 = (r - pr) ** 2 + (c - pc) ** 2
            key = (float(acc[r, c]), -d2)
            if best is None or key > best[0]:
                best = (key, r, c)
    return None if best is None else (best[1], best[2])


def watershed_from_outlet(mask, downstream, outlet_rc):
    """根据D8下游关系，从沟口反向搜索所有汇入该沟口的像元，返回流域掩膜。"""
    rows, cols = mask.shape
    out = np.zeros((rows, cols), dtype=bool)
    if outlet_rc is None:
        return out
    ups = upstream_lists(downstream, mask)
    start = int(outlet_rc[0]) * cols + int(outlet_rc[1])
    q = deque([start])
    seen = {start}
    while q:
        cur = q.popleft()
        r, c = cur // cols, cur % cols
        if mask[r, c]:
            out[r, c] = True
        for u in ups[cur]:
            if u not in seen:
                seen.add(u)
                q.append(u)
    return out
