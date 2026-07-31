/*
 * Linear array queue (no wraparound).
 *
 * Invariants:
 *   -1 <= front <= rear <= CAPACITY - 1
 *   empty  <=>  front == rear
 *   full   <=>  rear  == CAPACITY - 1
 *
 * Live elements are queue[front + 1 .. rear]. Slots below front are spent and
 * are never reclaimed -- that is inherent to this algorithm, not an oversight.
 */

#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#define CAPACITY 10

static int queue[CAPACITY];
static int front = -1;
static int rear = -1;

/* --- queue operations: pure state, no I/O ------------------------------- */

static inline bool queue_empty(void) { return front == rear; }
static inline bool queue_full(void) { return rear == CAPACITY - 1; }
static inline int queue_size(void) { return rear - front; }

/* Appends item. Returns false on overflow, leaving the queue untouched. */
static bool queue_enqueue(int item)
{
    if (queue_full())
        return false;
    queue[++rear] = item;
    return true;
}

/* Removes the front element into *out. Returns false on underflow. */
static bool queue_dequeue(int *out)
{
    if (queue_empty())
        return false;
    *out = queue[++front];
    return true;
}

/* Reads the front element into *out without removing it. */
static bool queue_peek(int *out)
{
    if (queue_empty())
        return false;
    *out = queue[front + 1];
    return true;
}

/* --- I/O ---------------------------------------------------------------- */

static void queue_display(void)
{
    if (queue_empty()) {
        puts("Queue is empty.");
        return;
    }
    fputs("Queue:", stdout);
    for (int i = front + 1; i <= rear; i++)
        printf(" %d", queue[i]);
    putchar('\n');
}

/*
 * Reads one line and parses a single integer from it. Returns false on EOF so
 * callers can shut down instead of spinning; a malformed line is re-prompted.
 */
static bool read_int(const char *prompt, int *out)
{
    char line[64];

    for (;;) {
        fputs(prompt, stdout);
        if (!fgets(line, sizeof line, stdin))
            return false;

        char *end;
        long value = strtol(line, &end, 10);
        while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r')
            end++;

        if (end != line && *end == '\0' && value >= INT_MIN && value <= INT_MAX) {
            *out = (int) value;
            return true;
        }
        puts("Please enter a whole number.");
    }
}

int main(void)
{
    static const char menu[] =
        "\n1. Insert element into queue\n"
        "2. Delete element from queue\n"
        "3. Display all elements of queue\n"
        "4. Peek\n"
        "5. Size of the queue\n"
        "6. Quit\n";

    for (;;) {
        int choice, item;

        fputs(menu, stdout);
        if (!read_int("\nEnter your choice: ", &choice))
            return EXIT_SUCCESS; /* EOF */

        switch (choice) {
        case 1:
            if (queue_full())
                puts("Queue overflow.");
            else if (read_int("Enter the element to insert: ", &item))
                queue_enqueue(item);
            else
                return EXIT_SUCCESS;
            break;

        case 2:
            if (queue_dequeue(&item))
                printf("Element deleted from queue is: %d\n", item);
            else
                puts("Queue underflow.");
            break;

        case 3:
            queue_display();
            break;

        case 4:
            if (queue_peek(&item))
                printf("Front element is: %d\n", item);
            else
                puts("Queue is empty.");
            break;

        case 5:
            printf("Size of the queue is: %d\n", queue_size());
            break;

        case 6:
            return EXIT_SUCCESS;

        default:
            puts("Wrong choice.");
        }
    }
}
