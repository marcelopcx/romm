<script setup lang="ts">
// TipsTab: where to find cheats, guides and walkthroughs for this game.
// Each card is a search on an external site, built from the game's name and
// platform, so nothing is scraped or stored and the links never go stale.
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RIcon } from "@/lib";
import type { DetailedRom } from "@/stores/roms";

defineOptions({ inheritAttrs: false });

const props = defineProps<{ rom: DetailedRom }>();

const { t } = useI18n();

type TipSource = {
  id: string;
  name: string;
  description: string;
  icon: string;
  url: string;
};

const gameName = computed(
  () => props.rom.name || props.rom.fs_name_no_tags || props.rom.fs_name_no_ext,
);
const platformName = computed(
  () => props.rom.platform_custom_name || props.rom.platform_display_name || "",
);

const sources = computed<TipSource[]>(() => {
  const game = encodeURIComponent(gameName.value);
  const withPlatform = encodeURIComponent(
    `${gameName.value} ${platformName.value} ${t("rom.tips-query-suffix")}`.trim(),
  );
  return [
    {
      id: "trucoteca",
      name: "Trucoteca",
      description: t("rom.tips-trucoteca"),
      icon: "mdi-controller",
      url: `https://trucoteca.com/?s=${game}`,
    },
    {
      id: "gamefaqs",
      name: "GameFAQs",
      description: t("rom.tips-gamefaqs"),
      icon: "mdi-book-open-page-variant",
      url: `https://gamefaqs.gamespot.com/search?game=${game}`,
    },
    {
      id: "youtube",
      name: "YouTube",
      description: t("rom.tips-youtube"),
      icon: "mdi-youtube",
      url: `https://www.youtube.com/results?search_query=${withPlatform}`,
    },
    {
      id: "google",
      name: "Google",
      description: t("rom.tips-google"),
      icon: "mdi-magnify",
      url: `https://www.google.com/search?q=${withPlatform}`,
    },
    {
      id: "hltb",
      name: "HowLongToBeat",
      description: t("rom.tips-hltb"),
      icon: "mdi-clock-outline",
      url: `https://howlongtobeat.com/?q=${game}`,
    },
  ];
});
</script>

<template>
  <div class="tips-tab">
    <p class="tips-tab__intro">
      {{ t("rom.tips-intro", { game: gameName }) }}
    </p>
    <div class="tips-tab__grid">
      <a
        v-for="source in sources"
        :key="source.id"
        class="tips-tab__card"
        :href="source.url"
        target="_blank"
        rel="noopener noreferrer"
      >
        <RIcon :icon="source.icon" size="22" class="tips-tab__icon" />
        <span class="tips-tab__text">
          <span class="tips-tab__name">{{ source.name }}</span>
          <span class="tips-tab__desc">{{ source.description }}</span>
        </span>
        <RIcon icon="mdi-open-in-new" size="16" class="tips-tab__out" />
      </a>
    </div>
  </div>
</template>

<style scoped>
.tips-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tips-tab__intro {
  margin: 0;
  font-size: 13px;
  color: var(--r-color-fg-muted);
}

.tips-tab__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.tips-tab__card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--r-color-border);
  border-radius: var(--r-radius-md);
  background: var(--r-color-surface);
  color: var(--r-color-fg);
  text-decoration: none;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.tips-tab__card:hover,
.tips-tab__card:focus-visible {
  border-color: var(--r-color-brand-primary);
  background: var(--r-color-surface-hover, var(--r-color-surface));
}

.tips-tab__icon {
  flex: none;
  color: var(--r-color-brand-primary);
}

.tips-tab__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.tips-tab__name {
  font-size: var(--r-font-size-md);
  font-weight: var(--r-font-weight-semibold);
}
.tips-tab__desc {
  font-size: 12px;
  color: var(--r-color-fg-muted);
}

.tips-tab__out {
  flex: none;
  color: var(--r-color-fg-faint);
}
</style>
