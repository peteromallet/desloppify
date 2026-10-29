/* C17 syntax probes; these constructs do not imply unreachable code. */
#include <stddef.h>

struct item { int value; };
union number { int integer; double real; };
enum kind { INTEGER, REAL };
typedef struct item item;
typedef int (*callback)(int);

_Static_assert(sizeof(int) >= 2, "int width");

int identity(int value) {
    return value;
}

int invoke(int (*function)(int), int value) {
    return function(value);
}

int (*select_callback(callback function))(int) {
    return function;
}

int process(int values[static 2], size_t count) {
    _Atomic int offset = 1;
    item current = (item){.value = values[0]};
    union number number = {.integer = values[1]};
    for (size_t i = 0; i < count; ++i) {
        current.value += values[i];
    }
    return _Generic(current.value, int: current.value + number.integer + offset,
                    default: 0);
}

#if defined(ENABLE_NATIVE)
int conditional(int value) {
    return value;
}
#else
int conditional(int value) {
    return -value;
}
#endif
