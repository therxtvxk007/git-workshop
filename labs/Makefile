# Build and run the six C lab assignments.
#
#   make          # compile everything into build/
#   make run      # compile, then run each program
#   make clean

CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -Werror -O2
BUILD   := build

PROGS := selection_sort stack_linked_list two_stacks stack_getmin sort_stack \
         rotate_linked_list

BINS := $(addprefix $(BUILD)/,$(PROGS))

.PHONY: all
all: $(BINS)

$(BUILD)/%: %.c | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $<

$(BUILD):
	mkdir -p $(BUILD)

.PHONY: run
run: $(BINS)
	@for bin in $(BINS); do \
		echo "=== $$bin ==="; \
		./$$bin || exit 1; \
		echo; \
	done

.PHONY: clean
clean:
	rm -rf $(BUILD)
