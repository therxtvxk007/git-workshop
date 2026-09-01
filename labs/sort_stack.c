/*
 * Lab Assignment: Sort a Stack Using Another Stack
 *
 * Sort a stack of integers so the smallest element ends up on top, using
 * nothing but push/pop/peek/isEmpty and one extra stack.
 *
 * The insertion loop is the one from the assignment: pop an element from the
 * original stack, move everything greater than it back out of the temporary
 * stack, then drop it in. That keeps the temporary stack non-decreasing from
 * bottom to top -- which means the largest, not the smallest, sits on top of
 * the temporary stack. Pouring it back into the original stack reverses it,
 * and the original stack then reads smallest-first from the top, exactly as
 * the assignment's expected output shows:
 *
 *     Input  (top -> bottom): 34, 3, 31, 98, 92, 23
 *     Output (top -> bottom): 3, 23, 31, 34, 92, 98
 *
 * The transfer back reuses the same temporary stack, so still only one extra
 * stack is in play.
 *
 * Time: O(n^2) in the worst case. Space: O(n) for the temporary stack.
 */

#include <assert.h>
#include <stdio.h>

#define MAX 100

typedef struct {
    int items[MAX];
    int top;
} Stack;

void init(Stack *s);
void push(Stack *s, int value);
int pop(Stack *s);
int peek(Stack *s);
int isEmpty(Stack *s);

void init(Stack *s)
{
    s->top = -1;
}

void push(Stack *s, int value)
{
    if (s->top + 1 == MAX) {
        printf("Stack Overflow: cannot push %d\n", value);
        return;
    }

    s->items[++s->top] = value;
}

int pop(Stack *s)
{
    if (isEmpty(s)) {
        printf("Stack Underflow: pop from an empty stack\n");
        return -1;
    }

    return s->items[s->top--];
}

int peek(Stack *s)
{
    if (isEmpty(s)) {
        printf("Stack is empty: nothing to peek\n");
        return -1;
    }

    return s->items[s->top];
}

int isEmpty(Stack *s)
{
    return s->top == -1;
}

/*
 * Sort s in place, smallest on top, using one temporary stack.
 */
void sortStack(Stack *s)
{
    Stack temp;
    init(&temp);

    while (!isEmpty(s)) {
        int value = pop(s);

        /* Make room for value by evicting everything above its place. */
        while (!isEmpty(&temp) && peek(&temp) > value) {
            push(s, pop(&temp));
        }

        push(&temp, value);
    }

    /* temp is largest-on-top; pouring it back flips it to smallest-on-top. */
    while (!isEmpty(&temp)) {
        push(s, pop(&temp));
    }
}

static void display(const char *label, Stack *s)
{
    printf("%s (top -> bottom): ", label);
    if (isEmpty(s)) {
        printf("(empty)");
    }
    for (int i = s->top; i >= 0; i--) {
        printf("%d%s", s->items[i], i > 0 ? ", " : "");
    }
    printf("\n");
}

/* Confirm the stack reads non-decreasing from the top downwards. */
static void checkSorted(Stack *s)
{
    for (int i = s->top; i > 0; i--) {
        assert(s->items[i] <= s->items[i - 1]);
    }
}

int main(void)
{
    Stack s;
    init(&s);

    /* Push bottom-first so the top ends up as 34, per the example. */
    int input[] = {23, 92, 98, 31, 3, 34};
    for (int i = 0; i < 6; i++) {
        push(&s, input[i]);
    }

    display("Input ", &s);
    sortStack(&s);
    display("Output", &s);

    int expected[] = {3, 23, 31, 34, 92, 98}; /* Top to bottom. */
    for (int i = 0; i < 6; i++) {
        assert(pop(&s) == expected[i]);
    }
    assert(isEmpty(&s));

    /* Empty and single-element stacks are already sorted. */
    sortStack(&s);
    assert(isEmpty(&s));

    push(&s, 42);
    sortStack(&s);
    assert(peek(&s) == 42);
    (void)pop(&s);

    /* Duplicates and negatives survive the sort. */
    int mixed[] = {5, -3, 5, 0, -3, 12};
    for (int i = 0; i < 6; i++) {
        push(&s, mixed[i]);
    }
    sortStack(&s);
    checkSorted(&s);
    assert(peek(&s) == -3);

    printf("sort_stack: all checks passed\n");
    return 0;
}
