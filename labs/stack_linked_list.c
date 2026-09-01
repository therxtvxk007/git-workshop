/*
 * Lab Assignment: Implement a Stack using a Linked List
 *
 * A singly linked list used as a stack. The head of the list is the top of
 * the stack, so push and pop are both O(1) and the stack has no fixed
 * capacity -- it grows until malloc fails.
 *
 * The assignment's signatures take no stack argument, so the list head is a
 * single file-scope variable.
 */

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

struct Node {
    int data;
    struct Node *next;
};

/* Top of the stack. NULL means empty. */
static struct Node *top = NULL;

void push(int data);
int pop(void);
int peek(void);
void display(void);

/* Insert at the head, which is the top of the stack. */
void push(int data)
{
    struct Node *node = malloc(sizeof(struct Node));
    if (node == NULL) {
        fprintf(stderr, "push: out of memory\n");
        exit(EXIT_FAILURE);
    }

    node->data = data;
    node->next = top;
    top = node;
}

/*
 * Remove and return the top element. On underflow there is no in-band value
 * left to return, so report it and return -1.
 */
int pop(void)
{
    if (top == NULL) {
        printf("Stack Underflow: pop from an empty stack\n");
        return -1;
    }

    struct Node *node = top;
    int data = node->data;

    top = node->next;
    free(node);

    return data;
}

/* Return the top element without removing it. */
int peek(void)
{
    if (top == NULL) {
        printf("Stack is empty: nothing to peek\n");
        return -1;
    }

    return top->data;
}

/* Print the stack from top to bottom. */
void display(void)
{
    if (top == NULL) {
        printf("Stack: (empty)\n");
        return;
    }

    printf("Stack: ");
    for (struct Node *cur = top; cur != NULL; cur = cur->next) {
        printf("%d%s", cur->data, cur->next != NULL ? " " : "");
    }
    printf("\n");
}

/* Release every remaining node so the demo leaves nothing allocated. */
static void destroy(void)
{
    while (top != NULL) {
        struct Node *node = top;
        top = top->next;
        free(node);
    }
}

int main(void)
{
    /* The walkthrough from the assignment. */
    printf("Push(10)  ");
    push(10);
    display();

    printf("Push(20)  ");
    push(20);
    display();

    printf("Push(30)  ");
    push(30);
    display();

    int popped = pop();
    printf("Pop()     Returns %d, ", popped);
    display();
    assert(popped == 30);

    int front = peek();
    printf("Peek()    Returns %d\n", front);
    assert(front == 20);

    /* The stack still holds 20 and 10, and peek did not remove anything. */
    assert(pop() == 20);
    assert(pop() == 10);

    /* Underflow is reported rather than dereferencing NULL. */
    assert(pop() == -1);
    assert(peek() == -1);
    display();

    destroy();
    printf("stack_linked_list: all checks passed\n");
    return 0;
}
