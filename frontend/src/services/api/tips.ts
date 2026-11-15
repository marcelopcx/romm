import api from "@/services/api";
import storeLanguage from "@/stores/language";

export type TipSection = { title: string; text: string };

export type TipBlock =
  | { type: "heading" | "paragraph"; text: string }
  | { type: "list"; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] };

export type TipPage = { title: string; source: string; blocks: TipBlock[] };

export type TipCategoryId = "basics" | "guide" | "items" | "enemies" | "data";

export type RomTips = {
  wikipedia: {
    title: string;
    language: string;
    summary: string;
    sections: TipSection[];
  } | null;
  categories: { id: TipCategoryId; pages: TipPage[] }[];
};

// The server gathers the guide from open wikis and translates it to the
// interface language, so the first request for a game can take a few seconds.
export async function getRomTips(romId: number): Promise<RomTips> {
  const { data } = await api.get<RomTips>(`/roms/${romId}/tips`, {
    params: { lang: storeLanguage().selectedLanguage.value },
    timeout: 120_000,
  });
  return data;
}
