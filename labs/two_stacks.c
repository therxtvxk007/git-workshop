/*
 * Lab Assignment: Two Stacks in a Single Array
 *
 * Two independent stacks share one array of MAX ints. Stack1 grows upward
 * from index 0, Stack2 grows downward from index MAX - 1, so neither has a
 * fixed half of the array -- either may use the whole array as long as the
 * other stays small. Space runs out only when the two tops meet.
 *
 * All four operations are O(1).
 */

#include <assert.h>
#include <stdio.h>

#define MAX 10

static int arr[MAX];
static int top1 = -1;  /* Stack1 is empty when top1 == -1. */
static int top2 = MAX; /* Stack2 is empty when top2 == MAX. */

void push1(int x);
void push2(int x);
int pop1(void);
int pop2(void);

/* The single overflow condition for both stacks: no free cell in between. */
static int isFull(void)
{
    return top1 + 1 == top2;
}

void push1(int x)
{
    if (isFull()) {
        printf("Stack Overflow: cannot push %d into Stack1\n", x);
        return;
    }

    arr[++top1] = x;
}

void push2(int x)
{
    if (isFull()) {
        printf("Stack Overflow: cannot push %d into Stack2\n", x);
        return;
    }

    arr[--top2] = x;
}

/* Underflow has no valid value to return, so report it and return -1. */
int pop1(void)
{
    if (top1 == -1) {
        printf("Stack Underflow: Stack1 is empty\n");
        return -1;
    }

    return arr[top1--];
}

int pop2(void)
{
    if (top2 == MAX) {
        printf("Stack Underflow: Stack2 is empty\n");
        return -1;
    }

    return arr[top2++];
}

static void display(void)
{
    printf("Stack1 (top -> bottom):");
    if (top1 == -1) {
        printf(" (empty)");
    }
    for (int i = top1; i >= 0; i--) {
        printf(" %d", arr[i]);
    }

    printf(" | Stack2 (top -> bottom):");
    if (top2 == MAX) {
        printf(" (empty)");
    }
    for (int i = top2; i < MAX; i++) {
        printf(" %d", arr[i]);
    }
    printf("\n");
}

int main(void)
{
    /* The example workflow from the assignment. */
    push1(10);
    push1(20);
    push2(30);
    push2(40);
    display();

    int a = pop1();
    printf("pop1() -> %d\n", a);
    assert(a == 20);

    int b = pop2();
    printf("pop2() -> %d\n", b);
    assert(b == 40);
    display();

    /* Either stack may claim the space the other is not using. */
    for (int i = 0; i < 8; i++) {
        push1(100 + i);
    }
    assert(top1 + 1 == top2); /* Full: one element left in Stack2. */

    /* One more push into either stack has to be refused. */
    push1(999);
    push2(999);
    assert(top1 + 1 == top2);

    /* Drain both stacks and confirm LIFO order all the way down. */
    for (int i = 7; i >= 0; i--) {
        assert(pop1() == 100 + i);
    }
    assert(pop1() == 10);
    assert(pop1() == -1); /* Underflow. */

    assert(pop2() == 30);
    assert(pop2() == -1); /* Underflow. */
    display();

    printf("two_stacks: all checks passed\n");
    return 0;
}
