# C Lab Assignments

Six data-structures lab assignments, solved in C. Each `.c` file is
self-contained: the required function with the exact signature the assignment
specifies, plus a `main` that runs the assignment's own example and asserts the
expected result, along with the edge cases the assignment leaves unstated.

## Build and run

```sh
cd labs
make run      # compile all six and run each one
make          # compile only, into build/
make clean
```

Everything compiles under `-std=c11 -Wall -Wextra -Werror` and runs clean under
AddressSanitizer and UndefinedBehaviorSanitizer.

## The assignments

| File | Assignment | Required signature |
| --- | --- | --- |
| [`selection_sort.c`](selection_sort.c) | Selection Sort | `void selectionSort(int arr[], int size)` |
| [`stack_linked_list.c`](stack_linked_list.c) | Stack using a linked list | `void push(int)`, `int pop(void)`, `int peek(void)`, `void display(void)` |
| [`two_stacks.c`](two_stacks.c) | Two stacks in a single array | `void push1(int)`, `void push2(int)`, `int pop1(void)`, `int pop2(void)` |
| [`stack_getmin.c`](stack_getmin.c) | Stack with O(1) `getMin()` in O(1) extra space | `void push(int)`, `void pop(void)`, `int top(void)`, `int getMin(void)` |
| [`sort_stack.c`](sort_stack.c) | Sort a stack using one more stack | `init`, `push`, `pop`, `peek`, `isEmpty` on `Stack *` |
| [`rotate_linked_list.c`](rotate_linked_list.c) | Rotate a linked list left by k | `struct Node *rotate(struct Node *head, int k)` |

### Selection Sort

Pick the smallest element of the unsorted suffix, swap it into place, repeat.
O(n²) comparisons, O(1) space, in place. The swap is skipped when the minimum
is already in position.

### Stack using a linked list

The list head is the top of the stack, so `push` and `pop` are O(1) and there is
no capacity limit. The assignment's signatures take no stack argument, so the
head is a single file-scope variable. Pop and peek on an empty stack print an
underflow message and return `-1` rather than dereferencing `NULL`.

### Two stacks in a single array

Stack1 grows up from index 0, Stack2 grows down from `MAX - 1`. Neither owns a
fixed half: either may use nearly the whole array as long as the other stays
small. The single overflow test for both is `top1 + 1 == top2`. All four
operations are O(1).

### Stack with O(1) `getMin()` and O(1) extra space

The only state beyond the stack itself is one variable, `minEle` — no second
stack. When a pushed element `x` is below the current minimum, the stack stores
`2*x - minEle` instead of `x`. That encoded value is strictly below the minimum
in force at the time, which is impossible for a real element, so it doubles as a
marker; and it carries the previous minimum, recoverable as `2*minEle - encoded`
when that cell is popped. `top()` reports `minEle` whenever the top cell is a
marker.

Cells are `long long` rather than `int`: `2*x - minEle` can fall outside the
`int` range even when every pushed element is a valid `int`, and signed overflow
is undefined behaviour. That is still one cell per element and one extra
variable — the O(1) extra-space requirement is about not introducing a second
data structure. The demo pushes `INT_MAX` then `INT_MIN` to exercise it.

### Sort a stack using another stack

The insertion loop is the one from the assignment: pop an element, move
everything greater than it out of the temporary stack, then drop it in.

One note on the assignment text: that loop leaves the temporary stack
*non-decreasing from bottom to top*, so the **largest** element is on top of it —
not the smallest, as step 3 of the assignment states. The two are reconciled by
pouring the temporary stack back into the original, which reverses the order;
the original stack then reads smallest-first from the top, which is what the
problem statement asks for and what the assignment's own expected output shows:

```
Input  (top -> bottom): 34, 3, 31, 98, 92, 23
Output (top -> bottom): 3, 23, 31, 34, 92, 98
```

The transfer back reuses the same temporary stack, so only one extra stack is
ever in play. O(n²) worst case, O(n) space.

### Rotate a linked list

Left rotation by `k`: the first `k` nodes move to the back. One pass finds the
length and the old tail, `k %= n` drops whole turns, then three pointer writes do
the rotation — close the list into a ring, cut it after node `k-1`. No node is
allocated or freed. O(n) time, O(1) space.

`k` is also normalised when negative, which makes a negative `k` the equivalent
right rotation (`-1` on a 5-node list is the same as left by 4).
