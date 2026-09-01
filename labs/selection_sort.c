/*
 * Lab Assignment: Selection Sort
 *
 * Sort an array of integers in ascending order with selection sort.
 * The array is sorted in place; no library sort is used.
 *
 * Time:  O(n^2) comparisons, O(n) swaps.
 * Space: O(1).
 */

#include <assert.h>
#include <stdio.h>

void selectionSort(int arr[], int size);

/*
 * Repeatedly pick the smallest element of the unsorted suffix arr[i..size-1]
 * and swap it into position i. Everything left of i is final once the pass
 * for i finishes.
 */
void selectionSort(int arr[], int size)
{
    for (int i = 0; i < size - 1; i++) {
        int minIndex = i;

        for (int j = i + 1; j < size; j++) {
            if (arr[j] < arr[minIndex]) {
                minIndex = j;
            }
        }

        /* Skip the write when the minimum is already in place. */
        if (minIndex != i) {
            int temp = arr[i];
            arr[i] = arr[minIndex];
            arr[minIndex] = temp;
        }
    }
}

static void printArray(const char *label, const int arr[], int size)
{
    printf("%s", label);
    for (int i = 0; i < size; i++) {
        printf("%d%s", arr[i], i + 1 < size ? ", " : "");
    }
    printf("\n");
}

static void checkSorted(const int arr[], int size)
{
    for (int i = 1; i < size; i++) {
        assert(arr[i - 1] <= arr[i]);
    }
}

int main(void)
{
    /* The example from the assignment. */
    int arr[] = {64, 25, 12, 22, 11};
    int size = (int)(sizeof(arr) / sizeof(arr[0]));

    printArray("Input:  ", arr, size);
    selectionSort(arr, size);
    printArray("Output: ", arr, size);

    int expected[] = {11, 12, 22, 25, 64};
    for (int i = 0; i < size; i++) {
        assert(arr[i] == expected[i]);
    }

    /* Edge cases: empty, single element, already sorted, all equal, reversed. */
    int empty[1] = {0};
    selectionSort(empty, 0);

    int one[] = {7};
    selectionSort(one, 1);
    assert(one[0] == 7);

    int sorted[] = {1, 2, 3, 4, 5};
    selectionSort(sorted, 5);
    checkSorted(sorted, 5);

    int equal[] = {4, 4, 4, 4};
    selectionSort(equal, 4);
    checkSorted(equal, 4);

    int reversed[] = {9, 7, 5, 3, 1, -2, -8};
    selectionSort(reversed, 7);
    checkSorted(reversed, 7);
    assert(reversed[0] == -8 && reversed[6] == 9);

    printf("selection_sort: all checks passed\n");
    return 0;
}
