<!-- The animated background. Pure CSS, no canvas, so it costs nothing on the
     main thread. Reduced motion turns the animations off. -->
<div class="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-void">
	<div
		class="absolute inset-0 opacity-70"
		style="background:radial-gradient(120% 80% at 50% -10%, #2e1065 0%, #12071f 45%, #05030b 100%)"
	></div>

	<div class="grid-floor absolute inset-x-0 bottom-0 h-[60vh] opacity-60"
		style="mask-image:linear-gradient(to top, black, transparent); -webkit-mask-image:linear-gradient(to top, black, transparent)"
	></div>

	<div
		class="absolute -left-40 top-10 h-[38rem] w-[38rem] rounded-full blur-[130px]"
		style="background:radial-gradient(circle, rgba(168,85,247,.35), transparent 65%); animation:pulse-glow 9s ease-in-out infinite"
	></div>
	<div
		class="absolute -right-32 top-1/3 h-[32rem] w-[32rem] rounded-full blur-[130px]"
		style="background:radial-gradient(circle, rgba(34,211,238,.22), transparent 65%); animation:pulse-glow 11s ease-in-out infinite 1.5s"
	></div>
	<div
		class="absolute left-1/3 -bottom-40 h-[30rem] w-[30rem] rounded-full blur-[140px]"
		style="background:radial-gradient(circle, rgba(236,72,153,.18), transparent 65%); animation:pulse-glow 13s ease-in-out infinite .8s"
	></div>

	<div
		class="scanline absolute inset-x-0 h-32 opacity-[0.07]"
		style="background:linear-gradient(to bottom, transparent, #c084fc, transparent)"
	></div>

	<div class="noise absolute inset-0 opacity-[0.035] mix-blend-overlay"></div>

	<div
		class="absolute inset-0 opacity-[0.06]"
		style="background:repeating-linear-gradient(to bottom, transparent 0 2px, rgba(0,0,0,.6) 2px 3px)"
	></div>
</div>
