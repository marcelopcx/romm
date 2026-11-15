import api from "@/services/api";
import storeLanguage from "@/stores/language";

export type TipSection = { title: string; text: string };

export type RomTips = {
  wikipedia: {
    title: string;
    language: string;
    summary: string;
    sections: TipSection[];
  } | null;
  cheats: {
    device: string;
    entries: { description: string; code: string }[];
  }[];
  guide: { title: string; pages: TipSection[] } | null;
};

// The server gathers the tips from open sources and translates them to the
// interface language, so the first request for a game can take a few seconds.
export async function getRomTips(romId: number): Promise<RomTips> {
  const { data } = await api.get<RomTips>(`/roms/${romId}/tips`, {
    params: { lang: storeLanguage().selectedLanguage.value },
    timeout: 90_000,
  });
  return data;
}
