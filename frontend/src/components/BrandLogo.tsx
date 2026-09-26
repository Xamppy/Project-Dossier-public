import Image from "next/image";

type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
};

/** Logo horizontal (ícono + wordmark). */
const heightMap = {
  sm: 40,
  md: 56,
  lg: 76,
};

export default function BrandLogo({ size = "md" }: BrandLogoProps) {
  const height = heightMap[size];
  const width = Math.round(height * 3.8);

  const shared = {
    alt: "TraceLens",
    width,
    height,
    priority: true,
    className: "brand-logo-img h-auto w-full max-w-full object-contain object-center",
    style: { height, maxHeight: height },
  };

  return (
    <span className="brand-logo-wrap relative inline-flex w-full max-w-[240px] items-center justify-center">
      <Image
        {...shared}
        alt={shared.alt}
        src="/tracelens-logo-dark.png"
        className={`${shared.className} brand-logo--dark`}
      />
      <Image
        {...shared}
        alt={shared.alt}
        src="/tracelens-logo-light.png"
        className={`${shared.className} brand-logo--light`}
      />
    </span>
  );
}
