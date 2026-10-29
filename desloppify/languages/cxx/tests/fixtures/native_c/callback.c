/* Valid C17: throw is an ordinary identifier, and the callback may return. */
void dispatch(void (*throw)(int), void (*cleanup)(void)) {
    throw(1);
    cleanup();
}

int unreachable(void) {
    return 1;
    return 2;
}
