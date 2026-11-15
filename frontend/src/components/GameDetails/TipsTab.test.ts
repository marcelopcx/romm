import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RomTips } from "@/services/api/tips";
import { detailedRomFixture } from "@/utils/rom.fixtures";
import TipsTab from "./TipsTab.vue";

vi.mock("vue-i18n");

// A plain function, not vi.fn(): vitest's mock bookkeeping leaves a rejected
// promise it observes unhandled, which fails the test that handles it fine.
let respond: (id: number) => Promise<RomTips> = () => Promise.resolve(TIPS);
const requested: number[] = [];
vi.mock("@/services/api/tips", () => ({
  getRomTips: (id: number) => {
    requested.push(id);
    return respond(id);
  },
}));

const TIPS: RomTips = {
  wikipedia: {
    title: "Crash Team Racing",
    language: "es",
    summary: "Un juego de carreras.",
    sections: [{ title: "Sistema de juego", text: "Se conduce con karts." }],
  },
  cheats: [
    {
      device: "GameShark",
      entries: [
        { description: "Vidas infinitas", code: "8001ABCD" },
        { description: "Dinero máximo", code: "8001FFFF" },
      ],
    },
  ],
  guide: { title: "CTR", pages: [{ title: "Controles", text: "Pulsa X." }] },
};

async function mountTab() {
  const wrapper = mount(TipsTab, {
    props: { rom: detailedRomFixture({ id: 7, name: "Crash Team Racing" }) },
    global: { stubs: { RIcon: true } },
  });
  await flushPromises();
  return wrapper;
}

describe("TipsTab", () => {
  beforeEach(() => {
    requested.length = 0;
    respond = () => Promise.resolve(TIPS);
  });

  it("shows the overview, cheats and guide inside the page", async () => {
    const wrapper = await mountTab();
    expect(requested).toEqual([7]);
    const text = wrapper.text();
    expect(text).toContain("Un juego de carreras.");
    expect(text).toContain("Se conduce con karts.");
    expect(text).toContain("Vidas infinitas");
    expect(wrapper.find("code").text()).toBe("8001ABCD");
    expect(text).toContain("Controles");
    // Everything is shown in place: no link takes the user elsewhere.
    expect(wrapper.find("a").exists()).toBe(false);
  });

  it("filters the cheats by description", async () => {
    const wrapper = await mountTab();
    await wrapper.find("input").setValue("dinero");
    const rows = wrapper.findAll(".tips-tab__cheat");
    expect(rows).toHaveLength(1);
    expect(rows[0].text()).toContain("Dinero máximo");
  });

  it("says so when no source has anything for the game", async () => {
    respond = () =>
      Promise.resolve({ wikipedia: null, cheats: [], guide: null });
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("rom.tips-empty");
  });

  it("shows an error when the request fails", async () => {
    respond = () => Promise.reject(new Error("boom"));
    const wrapper = await mountTab();
    expect(wrapper.text()).toContain("rom.tips-error");
  });
});
