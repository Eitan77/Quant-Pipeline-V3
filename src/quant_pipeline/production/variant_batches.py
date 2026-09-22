from __future__ import annotations

from collections import defaultdict


def plan_batches(requests, feature_grid, *, max_pairs, max_targets):
    """Input: noncanonical resolved requests. Preserve original request rows separately."""
    if max_pairs < 1 or max_targets < 1:
        raise ValueError("Batch limits must be positive")
    targets_by_pair = defaultdict(set)
    for row in requests:
        left, right = row["feature_a"], row["feature_b"]
        grid = feature_grid[left]
        if feature_grid[right] != grid:
            raise ValueError("Features do not share a decision grid")
        # Do not reorder left/right here: explicit cell coordinates have orientation.
        targets_by_pair[(grid, left, right)].add(row["target_id"])
    groups = defaultdict(list)
    for (grid, left, right), targets in targets_by_pair.items():
        groups[(grid, tuple(sorted(targets)))].append((left, right))
    for (grid, targets), pairs in sorted(groups.items()):
        pairs.sort()
        for p in range(0, len(pairs), max_pairs):
            block = pairs[p:p + max_pairs]
            features = sorted({f for pair in block for f in pair})
            positions = {f: i for i, f in enumerate(features)}
            for t in range(0, len(targets), max_targets):
                yield dict(grid=grid, pairs=block, features=features,
                           left=[positions[a] for a, _ in block],
                           right=[positions[b] for _, b in block],
                           targets=list(targets[t:t + max_targets]))


def scan_batch(scanner, batch, *, observations, packed_reader, target_reader,
               cluster_codes, fold_codes, resolutions=(3, 5, 10), row_chunk_size=None):
    """Readers return bounded arrays in exactly batch.features/batch.targets order."""
    def reader(start, end):
        packed = packed_reader(batch["features"], start, end)
        y = target_reader(batch["targets"], start, end)
        if packed.shape != (end - start, len(batch["features"])):
            raise ValueError("Packed reader axes mismatch")
        if y.shape != (end - start, len(batch["targets"])):
            raise ValueError("Target reader axes mismatch")
        return packed, batch["left"], batch["right"], y

    frames = scanner.scan_packed_resolutions(
        observations, len(batch["pairs"]), reader,
        resolutions=tuple(resolutions), target_count=len(batch["targets"]),
        row_chunk_size=row_chunk_size, cluster_codes=cluster_codes, fold_codes=fold_codes,
    )
    for resolution, frame in frames.items():
        records = frame.to_dict("records")
        expected = {(p, t) for p in range(len(batch["pairs"])) for t in range(len(batch["targets"]))}
        seen = set()
        for row in records:
            p = int(row["pair_index"])
            if "target_index" not in row and len(batch["targets"]) != 1:
                raise ValueError("Multi-target scan omitted target_index")
            t = int(row.get("target_index", 0))
            if (p, t) not in expected or (p, t) in seen:
                raise ValueError("Unexpected or duplicate scanner result")
            seen.add((p, t))
            left, right = batch["pairs"][p]
            yield {**row, "feature_a": left, "feature_b": right,
                   "target_id": batch["targets"][t], "resolution": int(resolution),
                   "v3_resolution": int(resolution)}
        if seen != expected:
            raise ValueError("Scanner result membership incomplete")
    if set(frames) != set(resolutions):
        raise ValueError("Scanner resolution coverage incomplete")
