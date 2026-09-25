"""Direct FP64 accumulation, without observation-by-pair temporary tensors."""
from functools import lru_cache
from pathlib import Path

import numpy as np

_PAIR_TILE = 4

_SOURCE = r'''
extern "C" __global__ void accumulate(
    const unsigned char* bins, const double* y, const long long* codes,
    const long long* left, const long long* right, const long long* target_columns, const long long* code_map,
    const long long* lookup, const long long* offsets, const long long* sizes,
    const long long* descriptors, long long rows, int features, int pairs,
    int targets, int input_targets, int families, int singles) {
    int pair = blockIdx.y * PAIR_TILE + threadIdx.x % PAIR_TILE;
    long long row = (long long)blockIdx.x * (blockDim.x / PAIR_TILE) + threadIdx.x / PAIR_TILE;
    if (row >= rows || pair >= pairs) return;
    unsigned char a = bins[row * features + left[pair]];
    unsigned char b = singles ? 0 : bins[row * features + right[pair]];
    if (a == 255 || b == 255) return;
    #if JOINT_CODES
    int cells[1] = {(int)code_map[a]};
    if (!singles) cells[0] = cells[0] * JOINT_CODES + code_map[b];
    #else
    int cells[3] = {a % 3, (a / 3) % 5, a / 15};
    if (!singles) {
        cells[0] = cells[0] * 3 + b % 3;
        cells[1] = cells[1] * 5 + (b / 3) % 5;
        cells[2] = cells[2] * 10 + b / 15;
    }
    #endif
    for (int family = 0; family < families; ++family) {
        long long group = codes[(long long)family * rows + row];
        if (group < 0 || group >= sizes[family]) continue;
        for (int resolution = 0; resolution < RESOLUTIONS; ++resolution) {
            long long task = lookup[offsets[family] + group * RESOLUTIONS + resolution];
            if (task < 0) continue;
            const long long* d = descriptors + task * 6;
            unsigned long long* n = (unsigned long long*)d[0];
            double* s = (double*)d[1];
            double* q = (double*)d[2];
            long long base = ((long long)pair * d[4] + group - d[3]) * d[5] + cells[resolution];
            long long stride = (long long)pairs * d[4] * d[5];
            for (int target = 0; target < targets; ++target) {
                double value = y[row * input_targets + target_columns[target]];
                if (!isfinite(value)) continue;
                long long index = base + target * stride;
                atomicAdd(n + index, 1ULL);
                atomicAdd(s + index, value);
                if (q) atomicAdd(q + index, value * value);
            }
        }
    }
}
'''


@lru_cache(maxsize=4)
def _kernel(pair_tile, joint_codes=0):
    import cupy
    options = ["--std=c++11", f"-DPAIR_TILE={pair_tile}", f"-DJOINT_CODES={joint_codes}",
               f"-DRESOLUTIONS={1 if joint_codes else 3}"]
    # A full toolkit is optional when CUDA runtime headers are installed by pip.
    try:
        import nvidia.cuda_runtime
        options.append("-I" + str(Path(nvidia.cuda_runtime.__path__[0]) / "include"))
    except ImportError:
        pass
    return cupy.RawKernel(_SOURCE, "accumulate", options=tuple(options))


class FusedSegmentedBatch:
    def __init__(self, live, left, right, target_columns=None, joint_codes=None):
        import torch
        self.live = live  # Keep all output allocations alive through launch.
        self.device = live[0][1].device
        self.families = sorted({task["grouping_id"] for task, _ in live})
        self.pair_tile = _PAIR_TILE
        self.kernel = _kernel(self.pair_tile, 0 if joint_codes is None else len(joint_codes))
        code_map = np.full(256, -1, np.int64)
        if joint_codes is not None:
            code_map[joint_codes] = np.arange(len(joint_codes))
        tables = []
        offsets, sizes, descriptors = [], [], []
        for family in self.families:
            size = max(task["group_stop"] for task, _ in live if task["grouping_id"] == family)
            offsets.append(sum(table.size for table in tables))
            sizes.append(size)
            table = np.full((size, 3 if joint_codes is None else 1), -1, np.int64)
            for index, (task, _) in enumerate(live):
                if task["grouping_id"] != family:
                    continue
                column = (3, 5, 10).index(task["resolution"]) if joint_codes is None else 0
                view = table[task["group_start"]:task["group_stop"], column]
                if (view >= 0).any():
                    raise ValueError("Overlapping fused subgroup partitions")
                view[:] = index
            tables.append(table.reshape(-1))
        for task, moments in live:
            descriptors.append([moments.n.data_ptr(), moments.s.data_ptr(),
                                0 if moments.q is None else moments.q.data_ptr(),
                                task["group_start"], moments.shape[2], moments.cells])
        self.arguments = [torch.as_tensor(value, dtype=torch.int64, device=self.device)
                          for value in (left, left if right is None else right,
                                        list(range(live[0][1].shape[0])) if target_columns is None else target_columns,
                                        code_map, np.concatenate(tables), offsets, sizes, descriptors)]

    def update(self, prepared, group_codes):
        import cupy
        import torch
        packed, y = (value.contiguous() for value in prepared)
        codes = (group_codes if isinstance(group_codes, torch.Tensor) else
                 torch.as_tensor(np.stack([group_codes[family] for family in self.families]),
                                 dtype=torch.int64, device=self.device))
        moments = self.live[0][1]
        targets, pairs, _, _ = moments.shape
        # Share Torch's stream and allocations; no copies or independent allocator
        # owns the accumulation buffers. Errors propagate rather than mixing paths.
        with cupy.cuda.Device(self.device.index), cupy.cuda.ExternalStream(torch.cuda.current_stream(self.device).cuda_stream):
            arrays = [cupy.from_dlpack(value) for value in (packed, y, codes, *self.arguments)]
            rows_per_block = 256 // self.pair_tile
            self.kernel(((len(packed) + rows_per_block - 1) // rows_per_block,
                         (pairs + self.pair_tile - 1) // self.pair_tile), (256,),
                        (*arrays, np.int64(len(packed)), np.int32(packed.shape[1]),
                         np.int32(pairs), np.int32(targets), np.int32(y.shape[1]), np.int32(len(self.families)),
                         np.int32(moments.singles)))


class ResidentEvidenceGrid:
    """Immutable verified inputs staged once, reused across pair/target batches."""
    def __init__(self, reader, device, *, reserve_bytes, row_chunk=250000, cancelled=lambda: False):
        import torch
        self.features = sorted(reader.grid["bins"])
        self.targets = sorted(reader.grid["targets"])
        self.families = sorted(reader.grid["groups"])
        self.feature_index = {name: i for i, name in enumerate(self.features)}
        self.target_index = {name: i for i, name in enumerate(self.targets)}
        self.family_index = {name: i for i, name in enumerate(self.families)}
        self.rows = reader.rows
        self.joint_batches = 0
        self.bytes = self.rows * (len(self.features) + 8*len(self.targets) + 8*len(self.families))
        free, _ = torch.cuda.mem_get_info(device)
        if self.bytes + reserve_bytes > free:
            raise MemoryError("Resident evidence inputs would consume accumulator headroom")
        self.bins = torch.empty((self.rows, len(self.features)), dtype=torch.uint8, device=device)
        self.y = torch.empty((self.rows, len(self.targets)), dtype=torch.float64, device=device)
        self.groups = torch.empty((len(self.families), self.rows), dtype=torch.int64, device=device)
        seen_codes = np.zeros(256, bool)
        for start in range(0, self.rows, row_chunk):
            if cancelled():
                raise InterruptedError("Resident evidence staging cancelled")
            stop = min(self.rows, start+row_chunk)
            bins = reader.read_columns("bins", self.features, start, stop)
            if np.any((bins >= 150) & (bins != 255)):
                raise ValueError("Invalid packed feature code")
            seen_codes |= np.bincount(bins.reshape(-1), minlength=256) > 0
            self.bins[start:stop].copy_(torch.from_numpy(bins))
            self.y[start:stop].copy_(torch.from_numpy(reader.read_columns("targets", self.targets, start, stop)))
            for family, index in self.family_index.items():
                self.groups[index, start:stop].copy_(torch.from_numpy(
                    np.array(reader.read_groups(family, start, stop), dtype=np.int64)))
        # Derive from the entire verified grid, never a sampled bin alphabet.
        self.joint_codes = np.flatnonzero(seen_codes[:150])

    def accumulate(self, live, pairs, target_ids, cancelled):
        left = [self.feature_index[pair[0]] for pair in pairs]
        right = None if live[0][1].singles else [self.feature_index[pair[1]] for pair in pairs]
        fused = FusedSegmentedBatch(live, left, right,
                                   [self.target_index[target] for target in target_ids])
        self._scan(fused, cancelled)

    def _scan(self, fused, cancelled):
        family_ids = [self.family_index[family] for family in fused.families]
        # Bound launch duration on display GPUs and retain cancellation points.
        for start in range(0, self.rows, 250000):
            if cancelled():
                raise InterruptedError("Resident evidence accumulation cancelled")
            stop = min(self.rows, start+250000)
            codes = self.groups[family_ids, start:stop].contiguous()
            fused.update((self.bins[start:stop], self.y[start:stop]), codes)

    def joint_batch(self, rows, pairs, target_ids, max_state_bytes, consume_block, cancelled):
        """Accumulate the exact packed-bin joint histogram once for all resolutions.

        Return None when its actual state does not fit; the caller then uses the
        ordinary fused path. Counts stay int64 and sums stay FP64 throughout.
        """
        from types import SimpleNamespace
        import torch
        from .segmented_scan import SegmentedMoments
        if not 1 <= len(self.joint_codes) <= 12:
            return None
        singles = rows[0]["task"]["state_kind"] == "single"
        cells = len(self.joint_codes) ** (1 if singles else 2)
        partitions = {}
        for row in rows:
            task = row["task"]
            key = (task["grouping_id"], task["group_start"], task["group_stop"])
            partitions.setdefault(key, task)
        required = sum(16*len(pairs)*len(target_ids)*(stop-start)*cells
                       for _, start, stop in partitions)
        if required > max_state_bytes:
            return None
        live = []
        by_partition = {}
        for key, task in partitions.items():
            shape = (len(target_ids), len(pairs), key[2]-key[1], cells)
            moments = SimpleNamespace(n=torch.zeros(shape, dtype=torch.int64, device=self.bins.device),
                                      s=torch.zeros(shape, dtype=torch.float64, device=self.bins.device),
                                      q=None, device=self.bins.device, shape=shape, cells=cells, singles=singles)
            live.append((task, moments)); by_partition[key] = moments
        left = [self.feature_index[pair[0]] for pair in pairs]
        right = None if singles else [self.feature_index[pair[1]] for pair in pairs]
        fused = FusedSegmentedBatch(live, left, right,
            [self.target_index[target] for target in target_ids], self.joint_codes)
        self._scan(fused, cancelled)
        projections = {}
        for resolution in (3, 5, 10):
            codes = self.joint_codes
            decoded = codes % 3 if resolution == 3 else (codes//3) % 5 if resolution == 5 else codes//15
            mapping = decoded if singles else (decoded[:, None]*resolution+decoded[None, :]).reshape(-1)
            projections[resolution] = torch.as_tensor(mapping, dtype=torch.int64, device=self.bins.device)
        results = []
        for row in rows:
            if cancelled():
                raise InterruptedError("Joint evidence cancelled before commit")
            task = row["task"]
            joint = by_partition[(task["grouping_id"], task["group_start"], task["group_stop"])]
            output = SegmentedMoments(pairs=len(pairs), targets=len(target_ids), groups=joint.shape[2],
                resolution=task["resolution"], singles=singles, device=self.bins.device,
                max_state_bytes=max_state_bytes, track_sumsq=False)
            indices = projections[task["resolution"]].expand(joint.shape)
            output.n.scatter_add_(-1, indices, joint.n)
            output.s.scatter_add_(-1, indices, joint.s)
            if consume_block is not None:
                consume_block(task, output, {"grid": row["grid"], "rows_evaluated": self.rows})
            results.append({"compute_status": "complete", "materialization_status": "recomputable",
                            "artifact": None, "bytes": 0, "sha256": None,
                            "populated_groups": int(output.n.any(dim=-1).sum().item())})
            del output
        self.joint_batches += 1
        return results
