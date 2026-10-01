import type { KbStandard, Preset } from "../types";
import { http } from "./http";

export const getKb = () => http<KbStandard[]>("/kb");
export const getPresets = () => http<Preset[]>("/kb/presets");
