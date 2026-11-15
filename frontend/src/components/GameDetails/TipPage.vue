<script setup lang="ts">
// TipPage: one guide page (a wiki article reduced to headings, paragraphs,
// lists and tables), collapsible so a long walkthrough stays scannable.
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import type { TipPage } from "@/services/api/tips";

defineOptions({ inheritAttrs: false });

defineProps<{ page: TipPage; open?: boolean }>();

const { t } = useI18n();

const ROWS_SHOWN = 25;

// Per-table state, keyed by the block's position on the page.
const filters = ref<Record<number, string>>({});
const expanded = ref<Record<number, boolean>>({});

function visibleRows(rows: string[][], index: number): string[][] {
  const needle = (filters.value[index] ?? "").trim().toLowerCase();
  const matching = needle
    ? rows.filter((row) =>
        row.some((cell) => cell.toLowerCase().includes(needle)),
      )
    : rows;
  return expanded.value[index] || needle
    ? matching
    : matching.slice(0, ROWS_SHOWN);
}
</script>

<template>
  <details class="tip-page" :open="open">
    <summary class="tip-page__title">
      {{ page.title }}
      <span class="tip-page__source">{{ page.source }}</span>
    </summary>

    <div class="tip-page__body">
      <template v-for="(block, i) in page.blocks" :key="i">
        <h4 v-if="block.type === 'heading'" class="tip-page__heading">
          {{ block.text }}
        </h4>
        <p v-else-if="block.type === 'paragraph'" class="tip-page__text">
          {{ block.text }}
        </p>
        <ul v-else-if="block.type === 'list'" class="tip-page__list">
          <li v-for="(item, j) in block.items" :key="j">{{ item }}</li>
        </ul>
        <div v-else-if="block.type === 'table'" class="tip-page__table-wrap">
          <input
            v-if="block.rows.length > ROWS_SHOWN"
            v-model="filters[i]"
            type="search"
            class="tip-page__filter"
            :placeholder="t('rom.tips-filter-rows')"
          />
          <div class="tip-page__scroll">
            <table class="tip-page__table">
              <thead>
                <tr>
                  <th v-for="(header, h) in block.headers" :key="h">
                    {{ header }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, r) in visibleRows(block.rows, i)" :key="r">
                  <td v-for="(cell, c) in row" :key="c">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <button
            v-if="block.rows.length > ROWS_SHOWN && !expanded[i] && !filters[i]"
            type="button"
            class="tip-page__more"
            @click="expanded[i] = true"
          >
            {{ t("rom.tips-show-all-rows", { n: block.rows.length }) }}
          </button>
        </div>
      </template>
    </div>
  </details>
</template>

<style scoped>
.tip-page {
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: var(--r-color-surface);
}

.tip-page__title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  font-size: var(--r-font-size-md);
  font-weight: var(--r-font-weight-semibold);
  color: var(--r-color-fg);
}

.tip-page__source {
  flex: none;
  font-size: 11px;
  font-weight: var(--r-font-weight-regular, 400);
  color: var(--r-color-fg-faint);
}

.tip-page__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 16px 16px;
}

.tip-page__heading {
  margin: 8px 0 0;
  font-size: 12px;
  font-weight: var(--r-font-weight-bold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--r-color-fg-faint);
}

.tip-page__text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--r-color-fg-secondary);
}

.tip-page__list {
  margin: 0;
  padding-left: 20px;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--r-color-fg-secondary);
}

.tip-page__table-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tip-page__filter {
  max-width: 320px;
  padding: 7px 12px;
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: var(--r-color-surface);
  color: var(--r-color-fg);
  font-size: 13px;
}

.tip-page__scroll {
  overflow-x: auto;
}

.tip-page__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.tip-page__table th {
  text-align: left;
  padding: 6px 10px;
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--r-color-fg-faint);
  border-bottom: 1px solid var(--r-color-border);
  white-space: nowrap;
}
.tip-page__table td {
  padding: 6px 10px;
  color: var(--r-color-fg-secondary);
  border-bottom: 1px solid var(--r-color-border);
  vertical-align: top;
}

.tip-page__more {
  align-self: flex-start;
  padding: 7px 14px;
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: transparent;
  color: var(--r-color-fg);
  font-size: 13px;
  cursor: pointer;
}
.tip-page__more:hover {
  border-color: var(--r-color-brand-primary);
}
</style>
