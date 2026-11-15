<script setup lang="ts">
// TipsTab: a guide for the game, laid out like the Media tab: a column of
// subtabs on the left (a sheet on phones) and the selected one on the right.
// The server gathers it from open wikis (overview, walkthrough, items, enemies
// and bosses, data lists) and translates it to the interface language; nothing
// here leaves RomM.
import { computed, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";
import SubtabNav, {
  type SubtabNavItem,
} from "@/components/GameDetails/SubtabNav.vue";
import TipPage from "@/components/GameDetails/TipPage.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useSubtabQuery } from "@/composables/useSubtabQuery";
import { RIcon } from "@/lib";
import {
  getRomTips,
  type RomTips,
  type TipCategoryId,
} from "@/services/api/tips";
import type { DetailedRom } from "@/stores/roms";
import { tabId, tabPanelId } from "@/utils/tabIds";

defineOptions({ inheritAttrs: false });

const props = defineProps<{ rom: DetailedRom }>();

const { t } = useI18n();
const { smAndDown } = useBreakpoint();

type Subtab = "overview" | TipCategoryId;
const SUBTABS: readonly Subtab[] = [
  "overview",
  "basics",
  "guide",
  "items",
  "enemies",
  "data",
];
const ICONS: Record<Subtab, string> = {
  overview: "mdi-text-box-outline",
  basics: "mdi-gamepad-variant-outline",
  guide: "mdi-map-legend",
  items: "mdi-treasure-chest-outline",
  enemies: "mdi-sword-cross",
  data: "mdi-table",
};

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

const selected = useSubtabQuery<Subtab>(
  "tips",
  (value) => SUBTABS.includes(value as Subtab),
  "overview",
);

const pagesBy = computed(() => {
  const map = new Map<TipCategoryId, RomTips["categories"][number]["pages"]>();
  for (const category of tips.value?.categories ?? [])
    map.set(category.id, category.pages);
  return map;
});

const available = computed<Subtab[]>(() =>
  SUBTABS.filter((id) =>
    id === "overview" ? !!tips.value?.wikipedia : pagesBy.value.has(id),
  ),
);

// A subtab this game has nothing for shows the first one it does have.
const active = computed<Subtab>(() =>
  available.value.includes(selected.value)
    ? selected.value
    : (available.value[0] ?? "overview"),
);

const subtabDefs = computed<SubtabNavItem<Subtab>[]>(() =>
  available.value.map((id) => ({
    id,
    label: t(`rom.tips-cat-${id}`),
    icon: ICONS[id],
    ...(id === "overview" ? {} : { badge: pagesBy.value.get(id)?.length ?? 0 }),
  })),
);

const isEmpty = computed(() => !!tips.value && available.value.length === 0);

// The sheet variant has no tabs to label the panels, so they stay sections.
const tabIdPrefix = useId();
function panelAttrs(id: Subtab): Record<string, string> {
  if (smAndDown.value) return {};
  return {
    id: tabPanelId(tabIdPrefix, id),
    role: "tabpanel",
    "aria-labelledby": tabId(tabIdPrefix, id),
  };
}
</script>

<template>
  <div class="r-tips">
    <div v-if="loading" class="r-tips__state">
      <RIcon icon="mdi-loading" size="20" class="r-tips__spin" />
      {{ t("rom.tips-loading") }}
    </div>
    <div v-else-if="failed" class="r-tips__state">
      {{ t("rom.tips-error") }}
    </div>
    <div v-else-if="isEmpty" class="r-tips__state">
      {{ t("rom.tips-empty") }}
    </div>

    <template v-else-if="tips">
      <SubtabNav
        v-if="smAndDown"
        :model-value="active"
        :items="subtabDefs"
        variant="menu"
        @update:model-value="selected = $event"
      />
      <aside v-else class="r-tips__sidebar">
        <SubtabNav
          :model-value="active"
          :items="subtabDefs"
          :id-prefix="tabIdPrefix"
          @update:model-value="selected = $event"
        />
      </aside>

      <div class="r-tips__content">
        <section
          v-if="active === 'overview' && tips.wikipedia"
          class="r-tips__panel"
          v-bind="panelAttrs('overview')"
        >
          <p class="r-tips__text">{{ tips.wikipedia.summary }}</p>
          <div
            v-for="section in tips.wikipedia.sections"
            :key="section.title"
            class="r-tips__block"
          >
            <h3 class="r-tips__heading">{{ section.title }}</h3>
            <p class="r-tips__text">{{ section.text }}</p>
          </div>
        </section>

        <section
          v-else-if="active !== 'overview'"
          :key="active"
          class="r-tips__panel"
          v-bind="panelAttrs(active)"
        >
          <TipPage
            v-for="(page, i) in pagesBy.get(active) ?? []"
            :key="`${active}-${page.title}`"
            :page="page"
            :open="i === 0"
          />
        </section>

        <p class="r-tips__sources">{{ t("rom.tips-sources") }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.r-tips {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  min-height: 0;
}

/* Phones stack the sheet trigger above the content. */
@media (max-width: 959px) {
  .r-tips {
    flex-direction: column;
    gap: 16px;
  }
}

.r-tips__state {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--r-color-fg-muted);
}
.r-tips__spin {
  animation: r-tips-spin 1s linear infinite;
}
@keyframes r-tips-spin {
  to {
    transform: rotate(360deg);
  }
}

.r-tips__sidebar {
  width: 220px;
  flex-shrink: 0;
  position: sticky;
  top: 0;
}

.r-tips__content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.r-tips__panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.r-tips__block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.r-tips__heading {
  margin: 8px 0 0;
  font-size: var(--r-font-size-md);
  font-weight: var(--r-font-weight-semibold);
  color: var(--r-color-fg);
}

.r-tips__text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--r-color-fg-secondary);
  white-space: pre-line;
}

.r-tips__sources {
  margin: 0;
  font-size: 11.5px;
  color: var(--r-color-fg-faint);
}
</style>
