import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "The Glass Box",
    short_name: "Glass Box",
    description: "Observable agent runtime UI",
    start_url: "/",
    display: "standalone",
    background_color: "#f4efe6",
    theme_color: "#f4efe6",
    icons: [
      {
        src: "/favicon.ico",
        sizes: "any",
        type: "image/x-icon",
      },
    ],
  };
}
