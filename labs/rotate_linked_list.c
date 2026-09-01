/*
 * Lab Assignment: Rotate a Linked List
 *
 * Rotate a singly linked list to the left by k places:
 *
 *     10 -> 20 -> 30 -> 40 -> 50, k = 4   =>   50 -> 10 -> 20 -> 30 -> 40
 *
 * The first k nodes move to the back. No node is allocated or freed; only
 * three next pointers change.
 *
 * Time: O(n). Space: O(1).
 */

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

struct Node {
    int data;
    struct Node *next;
};

struct Node *rotate(struct Node *head, int k);

struct Node *rotate(struct Node *head, int k)
{
    if (head == NULL || head->next == NULL) {
        return head;
    }

    /* Length, and the old tail, in one pass. */
    int n = 1;
    struct Node *oldTail = head;
    while (oldTail->next != NULL) {
        oldTail = oldTail->next;
        n++;
    }

    /* k % n drops whole turns. The second step maps a negative k (a right
     * rotation) onto the equivalent left rotation. */
    k %= n;
    if (k < 0) {
        k += n;
    }
    if (k == 0) {
        return head;
    }

    /* Walk to node k-1: it is the new tail, and node k is the new head. */
    struct Node *newTail = head;
    for (int i = 1; i < k; i++) {
        newTail = newTail->next;
    }

    struct Node *newHead = newTail->next;

    oldTail->next = head; /* Close the list into a ring... */
    newTail->next = NULL; /* ...then cut it after the new tail. */

    return newHead;
}

static struct Node *makeNode(int data)
{
    struct Node *node = malloc(sizeof(struct Node));
    if (node == NULL) {
        fprintf(stderr, "makeNode: out of memory\n");
        exit(EXIT_FAILURE);
    }

    node->data = data;
    node->next = NULL;
    return node;
}

/* Build a list from an array, returning its head. */
static struct Node *build(const int values[], int n)
{
    struct Node *head = NULL;
    struct Node *tail = NULL;

    for (int i = 0; i < n; i++) {
        struct Node *node = makeNode(values[i]);
        if (head == NULL) {
            head = node;
        } else {
            tail->next = node;
        }
        tail = node;
    }

    return head;
}

static void display(const char *label, struct Node *head)
{
    printf("%s", label);
    if (head == NULL) {
        printf("(empty)");
    }
    for (struct Node *cur = head; cur != NULL; cur = cur->next) {
        printf("%d%s", cur->data, cur->next != NULL ? " -> " : "");
    }
    printf("\n");
}

/* Assert the list is exactly `expected`, and that it is still NULL-terminated
 * at the right length -- a botched rotation leaves a cycle, so cap the walk. */
static void checkList(struct Node *head, const int expected[], int n)
{
    struct Node *cur = head;
    for (int i = 0; i < n; i++) {
        assert(cur != NULL);
        assert(cur->data == expected[i]);
        cur = cur->next;
    }
    assert(cur == NULL);
}

static void destroy(struct Node *head)
{
    while (head != NULL) {
        struct Node *node = head;
        head = head->next;
        free(node);
    }
}

int main(void)
{
    int values[] = {10, 20, 30, 40, 50};

    /* The example from the assignment. */
    struct Node *head = build(values, 5);
    display("Input:  ", head);
    head = rotate(head, 4);
    display("Output: ", head);

    int expected[] = {50, 10, 20, 30, 40};
    checkList(head, expected, 5);
    destroy(head);

    /* k = 0 and k = n leave the list unchanged. */
    head = build(values, 5);
    head = rotate(head, 0);
    checkList(head, values, 5);
    head = rotate(head, 5);
    checkList(head, values, 5);
    destroy(head);

    /* k larger than n wraps: 12 % 5 == 2. */
    head = build(values, 5);
    head = rotate(head, 12);
    int by2[] = {30, 40, 50, 10, 20};
    checkList(head, by2, 5);
    destroy(head);

    /* A negative k is the equivalent right rotation: -1 == left by 4. */
    head = build(values, 5);
    head = rotate(head, -1);
    checkList(head, expected, 5);
    destroy(head);

    /* Empty and single-node lists have nothing to rotate. */
    assert(rotate(NULL, 3) == NULL);

    head = build(values, 1);
    head = rotate(head, 7);
    checkList(head, values, 1);
    destroy(head);

    printf("rotate_linked_list: all checks passed\n");
    return 0;
}
