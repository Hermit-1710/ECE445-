#ifndef COMPILER_H_
#define COMPILER_H_

#include <stdint.h>

typedef uint32_t useconds_t;

#ifndef __INLINE
#define __INLINE inline
#endif

#ifndef __WEAK
#define __WEAK __attribute__((weak))
#endif

#ifndef __packed
#define __packed __attribute__((__packed__))
#endif

#ifndef UNUSED
#define UNUSED(x) ((void)(x))
#endif

#ifndef MIN
#define MIN(a, b) (((a) < (b)) ? (a) : (b))
#endif

#ifndef MAX
#define MAX(a, b) (((a) > (b)) ? (a) : (b))
#endif

#endif /* COMPILER_H_ */
