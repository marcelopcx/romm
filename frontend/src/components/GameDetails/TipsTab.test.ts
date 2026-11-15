import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { detailedRomFixture } from "@/utils/rom.fixtures";
import TipsTab from "./TipsTab.vue";

vi.mock("vue-i18n");

function hrefs(overrides = {}) {
  const wrapper = mount(TipsTab, {
    props: {
      rom: detailedRomFixture({
        id: 1,
        name: "Yu-Gi-Oh! Forbidden Memories",
        platform_display_name: "PlayStation",
        ...overrides,
      }),
    },
    global: { stubs: { RIcon: true } },
  });
  return wrapper.findAll("a").map((a) => a.attributes("href"));
}

describe("TipsTab", () => {
  it("links the game's name to Trucoteca, GameFAQs and the other sites", () => {
    const links = hrefs();
    expect(links[0]).toBe(
      "https://trucoteca.com/?s=Yu-Gi-Oh!%20Forbidden%20Memories",
    );
    expect(
      links.some((l) => l?.startsWith("https://gamefaqs.gamespot.com/")),
    ).toBe(true);
    expect(links).toHaveLength(5);
  });

  it("opens every link safely in a new tab", () => {
    const wrapper = mount(TipsTab, {
      props: { rom: detailedRomFixture({ id: 1, name: "Tetris" }) },
      global: { stubs: { RIcon: true } },
    });
    for (const a of wrapper.findAll("a")) {
      expect(a.attributes("target")).toBe("_blank");
      expect(a.attributes("rel")).toContain("noopener");
    }
  });

  it("falls back to the file name when the game has no name", () => {
    expect(hrefs({ name: null, fs_name_no_tags: "Some Game" })[0]).toBe(
      "https://trucoteca.com/?s=Some%20Game",
    );
  });
});
