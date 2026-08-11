/* Minimal declarations required by clang's mm_malloc.h for FerrumOS only.
 * Ring does not allocate through these functions; x86 intrinsic headers
 * include their declarations unconditionally while compiling ADX code. */
#ifndef FERRUM_RING_FREESTANDING_STDLIB_H
#define FERRUM_RING_FREESTANDING_STDLIB_H

#include <stddef.h>

void *malloc(size_t size);
void free(void *pointer);
int posix_memalign(void **pointer, size_t alignment, size_t size);

#endif
