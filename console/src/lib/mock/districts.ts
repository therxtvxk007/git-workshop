import type { District } from "@/lib/api/types";

/**
 * A fixed slice of the Indian district universe.
 *
 * Real LGD codes, names and approximate centroids, so the map and the state
 * filter behave the way they will against live data. The *forecasts* attached
 * to these districts are synthetic; the geography is not, because a demo that
 * invents districts teaches the wrong mental model of the filter cardinality.
 */
const RAW: ReadonlyArray<[string, string, string, string, number, number, number]> = [
  ["532", "Ahmedabad", "Gujarat", "GJ", 23.03, 72.58, 8059441],
  ["055", "Amritsar", "Punjab", "PB", 31.63, 74.87, 2490656],
  ["243", "Bahraich", "Uttar Pradesh", "UP", 27.57, 81.6, 3487731],
  ["583", "Bengaluru Urban", "Karnataka", "KA", 12.97, 77.59, 9621551],
  ["199", "Bhagalpur", "Bihar", "BR", 25.24, 86.98, 3037766],
  ["413", "Bhopal", "Madhya Pradesh", "MP", 23.26, 77.41, 2371061],
  ["605", "Chennai", "Tamil Nadu", "TN", 13.08, 80.27, 4646732],
  ["339", "Cuttack", "Odisha", "OR", 20.46, 85.88, 2624470],
  ["197", "Darbhanga", "Bihar", "BR", 26.15, 85.9, 3937385],
  ["120", "Dehradun", "Uttarakhand", "UK", 30.32, 78.03, 1696694],
  ["330", "Dhenkanal", "Odisha", "OR", 20.65, 85.6, 1192948],
  ["093", "Gurugram", "Haryana", "HR", 28.46, 77.03, 1514432],
  ["146", "Guwahati (Kamrup M)", "Assam", "AS", 26.14, 91.74, 1253938],
  ["252", "Gorakhpur", "Uttar Pradesh", "UP", 26.76, 83.37, 4440895],
  ["551", "Hyderabad", "Telangana", "TG", 17.39, 78.49, 3943323],
  ["338", "Jagatsinghpur", "Odisha", "OR", 20.25, 86.17, 1136971],
  ["112", "Jaipur", "Rajasthan", "RJ", 26.91, 75.79, 6626178],
  ["370", "Jamshedpur (E Singhbhum)", "Jharkhand", "JH", 22.8, 86.19, 2293919],
  ["521", "Jodhpur", "Rajasthan", "RJ", 26.24, 73.02, 3687165],
  ["276", "Kanpur Nagar", "Uttar Pradesh", "UP", 26.45, 80.33, 4581268],
  ["588", "Kozhikode", "Kerala", "KL", 11.26, 75.78, 3086293],
  ["300", "Lucknow", "Uttar Pradesh", "UP", 26.85, 80.95, 4589838],
  ["414", "Ludhiana", "Punjab", "PB", 30.9, 75.86, 3498739],
  ["501", "Madurai", "Tamil Nadu", "TN", 9.93, 78.12, 3038252],
  ["424", "Mumbai Suburban", "Maharashtra", "MH", 19.13, 72.87, 9356962],
  ["245", "Muzaffarpur", "Bihar", "BR", 26.12, 85.39, 4801062],
  ["097", "Nagpur", "Maharashtra", "MH", 21.15, 79.09, 4653570],
  ["097b", "Nashik", "Maharashtra", "MH", 20.01, 73.79, 6107187],
  ["094", "New Delhi", "Delhi", "DL", 28.61, 77.21, 142004],
  ["343", "Patna", "Bihar", "BR", 25.59, 85.14, 5838465],
  ["357", "Puri", "Odisha", "OR", 19.81, 85.83, 1698730],
  ["525", "Pune", "Maharashtra", "MH", 18.52, 73.86, 9429408],
  ["469", "Raipur", "Chhattisgarh", "CT", 21.25, 81.63, 4063872],
  ["163", "Ranchi", "Jharkhand", "JH", 23.34, 85.31, 2914253],
  ["314", "Srinagar", "Jammu and Kashmir", "JK", 34.08, 74.8, 1236829],
  ["330b", "Surat", "Gujarat", "GJ", 21.17, 72.83, 6081322],
  ["309", "Thiruvananthapuram", "Kerala", "KL", 8.52, 76.94, 3301427],
  ["350", "Varanasi", "Uttar Pradesh", "UP", 25.32, 82.97, 3676841],
  ["019", "Kolkata", "West Bengal", "WB", 22.57, 88.36, 4496694],
  ["023", "Murshidabad", "West Bengal", "WB", 24.18, 88.27, 7103807],
];

export const MOCK_DISTRICTS: District[] = RAW.map(
  ([code, name, state, stateCode, lat, lon, population]) => ({
    district_id: `LGD-${code}`,
    name,
    state,
    state_code: stateCode,
    centroid: { lat, lon },
    population,
    is_demo: true,
  }),
);

export const MOCK_STATES = [...new Set(MOCK_DISTRICTS.map((d) => d.state))].sort();
