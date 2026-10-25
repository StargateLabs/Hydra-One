#pragma once
#include <cstddef>
#include <cstdint>
#include <limits>

namespace strata::core {
// Pointer/arena extents must fit both size_t and signed 64-bit byte counters.
inline constexpr uint64_t kMemoryExtentMax =
    (uint64_t(SIZE_MAX) < uint64_t(INT64_MAX) ? uint64_t(SIZE_MAX) : uint64_t(INT64_MAX));

inline bool checked_memory_add(uint64_t a, uint64_t b, uint64_t& out) noexcept {
    if (a > kMemoryExtentMax || b > kMemoryExtentMax - a) return false;
    out = a + b; return true;
}
inline bool checked_memory_mul(uint64_t count, uint64_t width, uint64_t& out) noexcept {
    if (width && count > kMemoryExtentMax / width) return false;
    out = count * width; return true;
}
// Failure leaves the counter unchanged. Counting and real carving use one rule.
inline bool checked_memory_take(uint64_t& used, uint64_t cap, uint64_t count,
                                uint64_t width, uint64_t padding, uint64_t align,
                                uint64_t& bytes) noexcept {
    uint64_t raw, rounded, next;
    if (!align || (align & (align - 1)) || cap > kMemoryExtentMax ||
        !checked_memory_mul(count, width, raw) ||
        !checked_memory_add(raw, padding, raw) ||
        !checked_memory_add(raw, align - 1, rounded)) return false;
    rounded &= ~(align - 1);
    if (!checked_memory_add(used, rounded, next) || next > cap) return false;
    bytes = rounded; used = next; return true;
}
} // namespace strata::core
