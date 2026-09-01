/*
 * Lab Assignment: Stack with O(1) getMin() and O(1) Extra Space
 *
 * push, pop, top and getMin are all O(1), and the only state beyond the stack
 * itself is one variable, minEle -- no second stack, no auxiliary array.
 *
 * The trick: when a new element x is smaller than the current minimum, the
 * stack does not store x. It stores the encoded value 2*x - minEle, which is
 * strictly less than x and therefore strictly less than the minimum recorded
 * at that moment. That "impossible" value is the flag saying this cell is a
 * minimum-change marker, and it also carries the previous minimum, since
 *
 *     previous minimum = 2 * minEle - encoded
 *
 * so pop can restore it. Any stored value >= minEle is a real element.
 *
 * Cells are long long rather than int so 2*x - minEle cannot overflow for
 * int inputs; the encoded value can sit outside the int range even when every
 * pushed element is a valid int. That is still one cell per element and one
 * extra variable -- the O(1) extra-space requirement is about not adding a
 * second data structure.
 */

#include <assert.h>
#include <stdio.h>

#define MAX 100

static long long stack[MAX];
static int topIndex = -1;
static long long minEle = 0; /* Meaningful only while the stack is non-empty. */

void push(int x);
void pop(void);
int top(void);
int getMin(void);

static int isEmpty(void)
{
    return topIndex == -1;
}

void push(int x)
{
    if (topIndex + 1 == MAX) {
        printf("Stack Overflow: cannot push %d\n", x);
        return;
    }

    if (isEmpty()) {
        stack[++topIndex] = x;
        minEle = x;
        return;
    }

    if (x < minEle) {
        /* Encode: store a value below the old minimum, then adopt x. */
        stack[++topIndex] = 2LL * x - minEle;
        minEle = x;
    } else {
        stack[++topIndex] = x;
    }
}

void pop(void)
{
    if (isEmpty()) {
        printf("Stack Underflow: pop from an empty stack\n");
        return;
    }

    long long value = stack[topIndex--];

    /* An encoded cell is the one that pushed minEle down; undo it. */
    if (value < minEle) {
        minEle = 2 * minEle - value;
    }
}

/*
 * The top cell is either a real element or an encoded marker. A marker means
 * the real element it stands for is exactly the current minimum.
 */
int top(void)
{
    if (isEmpty()) {
        printf("Stack is empty: no top element\n");
        return -1;
    }

    long long value = stack[topIndex];
    return (int)(value < minEle ? minEle : value);
}

int getMin(void)
{
    if (isEmpty()) {
        printf("Stack is empty: no minimum\n");
        return -1;
    }

    return (int)minEle;
}

int main(void)
{
    /* The example from the assignment. */
    push(3);
    push(5);
    printf("getMin() -> %d\n", getMin());
    assert(getMin() == 3);
    assert(top() == 5);

    push(2);
    push(1);
    printf("getMin() -> %d\n", getMin());
    assert(getMin() == 1);
    assert(top() == 1); /* Encoded cell still reports the real element. */

    pop();
    printf("getMin() -> %d\n", getMin());
    assert(getMin() == 2);
    assert(top() == 2);

    /* Unwind the rest and watch the minimum walk back up. */
    pop();
    assert(getMin() == 3 && top() == 5);
    pop();
    assert(getMin() == 3 && top() == 3);
    pop();
    assert(getMin() == -1 && top() == -1); /* Empty. */
    pop();                                 /* Underflow is reported, not fatal. */

    /* A descending run makes every push an encoded one. */
    for (int x = 5; x >= 1; x--) {
        push(x);
        assert(getMin() == x && top() == x);
    }
    for (int x = 1; x <= 5; x++) {
        assert(getMin() == x);
        pop();
    }
    assert(getMin() == -1);

    /* Extreme values: the encoding leaves the int range, the answers do not. */
    push(2147483647);
    push(-2147483648);
    assert(getMin() == -2147483648);
    assert(top() == -2147483648);
    pop();
    assert(getMin() == 2147483647 && top() == 2147483647);
    pop();

    printf("stack_getmin: all checks passed\n");
    return 0;
}
