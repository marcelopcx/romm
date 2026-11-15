import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import type { RomTips } from "@/services/api/tips";
import { detailedRomFixture } from "@/utils/rom.fixtures";
import TipsTab from "./TipsTab.vue";

vi.mock("vue-i18n");

// A plain function, not vi.fn(): vitest's mock bookkeeping leaves a rejected
// promise it observes unhandled, which fails the test that handles it fine.
const TIPS: RomTips = {
  wikipedia: {
    title: "Yu-Gi-Oh! Forbidden Memories",
    language: "es",
    summary: "Un juego de cartas.",
    sections: [{ title: "Historia", text: "Viaje al antiguo Egipto." }],
  },
  categories: [
    {
      id: "data",
      pages: [
        {
          title: "Lista de cartas",
          source: "Fandom",
          blocks: [
            {
              type: "table",
              headers: ["Carta", "Password", "Coste"],
              rows: [
                ["Blue-eyes White Dragon", "89631139", "999,999"],
                ["Mystical Elf", "15025844", "160"],
              ],
            },
          ],
        },
      ],
    },
    {
      id: "items",
      pages: [
        {
          title: "Objetos",
          source: "StrategyWiki",
          blocks: [{ type: "paragraph", text: "Busca el cofre raro." }],
        },
      ],
    },
  ],
};

let respond: (id: number) => Promise<RomTips> = () => Promise.resolve(TIPS);
const requested: number[] = [];
vi.mock("@/services/api/tips", () => ({
  getRomTips: (id: number) => {
    requested.push(id);
    return respond(id);
  },
}));

let router: Router;

async function mountTab(subtab?: string) {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/rom/:id", component: { template: "<div />" } }],
  });
  await router.push({
    path: "/rom/7",
    query: subtab ? { tab: "tips", subtab } : { tab: "tips" },
  });
  const wrapper = mount(TipsTab, {
    props: { rom: detailedRomFixture({ id: 7, name: "Yu-Gi-Oh!" }) },
    global: { plugins: [router], stubs: { RIcon: true, SubtabNav: true } },
  });
  await flushPromises();
  return wrapper;
}

describe("TipsTab", () => {
  beforeEach(() => {
    requested.length = 0;
    respond = () => Promise.resolve(TIPS);
  });

  it("lays the guide out as subtabs, one per kind of content it has", async () => {
    const wrapper = await mountTab();
    expect(requested).toEqual([7]);
    const nav = wrapper.findComponent({ name: "SubtabNav" });
    const items = nav.props("items") as { id: string; badge?: number }[];
    expect(items.map((i) => i.id)).toEqual(["overview", "items", "data"]);
    expect(items.find((i) => i.id === "data")?.badge).toBe(1);
  });

  it("opens on the overview and shows it in place", async () => {
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("Un juego de cartas.");
    expect(wrapper.text()).toContain("Viaje al antiguo Egipto.");
    // Everything is shown in place: no link takes the user elsewhere.
    expect(wrapper.find("a").exists()).toBe(false);
  });

  it("shows a data table with the shop passwords", async () => {
    const wrapper = await mountTab();
    wrapper
      .findComponent({ name: "SubtabNav" })
      .vm.$emit("update:modelValue", "data");
    await flushPromises();
    const cells = wrapper.findAll("td").map((td) => td.text());
    expect(cells).toContain("89631139");
    expect(wrapper.findAll("th").map((th) => th.text())).toEqual([
      "Carta",
      "Password",
      "Coste",
    ]);
  });

  it("starts on the first subtab the game has when there is no overview", async () => {
    respond = () => Promise.resolve({ ...TIPS, wikipedia: null });
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("Objetos");
    expect(wrapper.text()).toContain("Busca el cofre raro.");
  });

  it("says so when no source has anything for the game", async () => {
    respond = () => Promise.resolve({ wikipedia: null, categories: [] });
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("rom.tips-empty");
  });

  it("shows an error when the request fails", async () => {
    respond = () => Promise.reject(new Error("boom"));
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("rom.tips-error");
  });
});
