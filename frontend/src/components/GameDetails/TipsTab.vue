<script setup lang="ts">
// TipsTab: what the open sources say about this game, shown in place. The
// server gathers it (Wikipedia overview, cheat codes from libretro, StrategyWiki
// guide pages) and translates it to the interface language; nothing here
// leaves RomM.
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RIcon } from "@/lib";
import { getRomTips, type RomTips } from "@/services/api/tips";
import type { DetailedRom } from "@/stores/roms";

defineOptions({ inheritAttrs: false });

const props = defineProps<{ rom: DetailedRom }>();

const { t } = useI18n();

const tips = ref<RomTips | null>(null);
const loading = ref(true);
const failed = ref(false);

let requestId = 0;
watch(
  () => props.rom.id,
  async (id) => {
    const current = ++requestId;
    loading.value = true;
    failed.value = false;
    tips.value = null;
    try {
      const data = await getRomTips(id);
      if (current === requestId) tips.value = data;
    } catch {
      if (current === requestId) failed.value = true;
    } finally {
      if (current === requestId) loading.value = false;
    }
  },
  { immediate: true },
);

const isEmpty = computed(
  () =>
    !!tips.value &&
    !tips.value.wikipedia &&
    !tips.value.guide &&
    tips.value.cheats.length === 0,
);

const filter = ref("");
const showAll = ref(false);
const CHEATS_SHOWN = 40;

const cheatGroups = computed(() => {
  const needle = filter.value.trim().toLowerCase();
  return (tips.value?.cheats ?? []).map((group) => {
    const matching = needle
      ? group.entries.filter((e) =>
          e.description.toLowerCase().includes(needle),
        )
      : group.entries;
    return {
      device: group.device,
      total: matching.length,
      entries:
        showAll.value || needle ? matching : matching.slice(0, CHEATS_SHOWN),
    };
  });
});
</script>

<template>
  <div class="tips-tab">
    <div v-if="loading" class="tips-tab__state">
      <RIcon icon="mdi-loading" size="20" class="tips-tab__spin" />
      {{ t("rom.tips-loading") }}
    </div>
    <div v-else-if="failed" class="tips-tab__state">
      {{ t("rom.tips-error") }}
    </div>
    <div v-else-if="isEmpty" class="tips-tab__state">
      {{ t("rom.tips-empty") }}
    </div>

    <template v-else-if="tips">
      <!-- Overview -->
      <section v-if="tips.wikipedia" class="tips-tab__section">
        <h3 class="tips-tab__heading">{{ t("rom.tips-overview") }}</h3>
        <p class="tips-tab__text">{{ tips.wikipedia.summary }}</p>
        <div
          v-for="section in tips.wikipedia.sections"
          :key="section.title"
          class="tips-tab__block"
        >
          <h4 class="tips-tab__subheading">{{ section.title }}</h4>
          <p class="tips-tab__text">{{ section.text }}</p>
        </div>
      </section>

      <!-- Cheat codes -->
      <section v-if="tips.cheats.length" class="tips-tab__section">
        <h3 class="tips-tab__heading">{{ t("rom.tips-cheats") }}</h3>
        <input
          v-model="filter"
          type="search"
          class="tips-tab__filter"
          :placeholder="t('rom.tips-cheats-filter')"
        />
        <div
          v-for="group in cheatGroups"
          :key="group.device"
          class="tips-tab__block"
        >
          <h4 class="tips-tab__subheading">
            {{ group.device }}
            <span class="tips-tab__count">{{ group.total }}</span>
          </h4>
          <ul class="tips-tab__cheats">
            <li
              v-for="(entry, i) in group.entries"
              :key="`${i}-${entry.code}`"
              class="tips-tab__cheat"
            >
              <span class="tips-tab__cheat-desc">{{ entry.description }}</span>
              <code class="tips-tab__code">{{ entry.code }}</code>
            </li>
          </ul>
        </div>
        <button
          v-if="!showAll && !filter"
          type="button"
          class="tips-tab__more"
          @click="showAll = true"
        >
          {{ t("rom.tips-show-all") }}
        </button>
      </section>

      <!-- Guide -->
      <section v-if="tips.guide" class="tips-tab__section">
        <h3 class="tips-tab__heading">{{ t("rom.tips-guide") }}</h3>
        <details
          v-for="(page, i) in tips.guide.pages"
          :key="page.title"
          class="tips-tab__page"
          :open="i === 0"
        >
          <summary class="tips-tab__page-title">{{ page.title }}</summary>
          <p class="tips-tab__text">{{ page.text }}</p>
        </details>
      </section>

      <p class="tips-tab__sources">{{ t("rom.tips-sources") }}</p>
    </template>
  </div>
</template>

<style scoped>
.tips-tab {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.tips-tab__state {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--r-color-fg-muted);
}
.tips-tab__spin {
  animation: tips-spin 1s linear infinite;
}
@keyframes tips-spin {
  to {
    transform: rotate(360deg);
  }
}

.tips-tab__section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tips-tab__heading {
  margin: 0;
  font-size: var(--r-font-size-md);
  font-weight: var(--r-font-weight-semibold);
  color: var(--r-color-fg);
}
.tips-tab__subheading {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: var(--r-font-weight-bold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--r-color-fg-faint);
}
.tips-tab__count {
  margin-left: 6px;
  font-weight: var(--r-font-weight-regular, 400);
  color: var(--r-color-fg-muted);
}

.tips-tab__text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--r-color-fg-secondary);
  white-space: pre-line;
}

.tips-tab__filter {
  max-width: 360px;
  padding: 8px 12px;
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: var(--r-color-surface);
  color: var(--r-color-fg);
  font-size: 13px;
}

.tips-tab__cheats {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}
.tips-tab__cheat {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
  border-bottom: 1px solid var(--r-color-border);
  font-size: 13px;
}
.tips-tab__cheat-desc {
  color: var(--r-color-fg-secondary);
  min-width: 0;
}
.tips-tab__code {
  flex: none;
  max-width: 55%;
  font-family: var(--r-font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--r-color-fg-muted);
  word-break: break-all;
  text-align: right;
}

.tips-tab__more {
  align-self: flex-start;
  padding: 8px 14px;
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: transparent;
  color: var(--r-color-fg);
  font-size: 13px;
  cursor: pointer;
}
.tips-tab__more:hover {
  border-color: var(--r-color-brand-primary);
}

.tips-tab__page {
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  padding: 10px 14px;
  background: var(--r-color-surface);
}
.tips-tab__page-title {
  cursor: pointer;
  font-size: 13.5px;
  font-weight: var(--r-font-weight-semibold);
  color: var(--r-color-fg);
}
.tips-tab__page[open] .tips-tab__page-title {
  margin-bottom: 8px;
}

.tips-tab__sources {
  margin: 0;
  font-size: 11.5px;
  color: var(--r-color-fg-faint);
}
</style>
