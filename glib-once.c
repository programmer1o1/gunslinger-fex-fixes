#include <stdint.h>
extern int g_once_init_enter(volatile void *location);
extern void g_once_init_leave(volatile void *location, uintptr_t result);

int g_once_init_enter_pointer(void *location) {
    return g_once_init_enter(location);
}

void g_once_init_leave_pointer(void *location, void *result) {
    g_once_init_leave(location, (uintptr_t)result);
}
