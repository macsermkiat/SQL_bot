/**
 * Forward-motion starfield: spacecraft flying through stars.
 * Stars emanate from center, accelerate outward with motion trails.
 */
(function () {
    "use strict";

    var canvas = document.getElementById("starfield");
    if (!canvas) return;

    var ctx = canvas.getContext("2d");

    // Configuration
    var CONFIG = {
        starCount: 400,
        baseSpeed: 0.015,        // moderate speed (not warp)
        speedVariance: 0.008,
        trailLength: 0.35,       // trail length multiplier
        spawnRadius: 0.02,       // spawn stars close to center
        maxRadius: 2.5,          // max star size when close
        minRadius: 0.3,          // min star size when far
        centerX: 0.5,            // vanishing point X (0-1)
        centerY: 0.48,           // vanishing point Y (slightly above center)
        colorShift: true,        // shift to blue when fast
        nebulaParticles: 25,     // subtle nebula dust particles
    };

    // Color palette for stars
    var COLORS = [
        { r: 255, g: 255, b: 255 },  // white
        { r: 200, g: 220, b: 255 },  // cool blue
        { r: 180, g: 200, b: 255 },  // steel blue
        { r: 220, g: 200, b: 255 },  // lavender
        { r: 255, g: 240, b: 220 },  // warm white
        { r: 100, g: 180, b: 255 },  // bright blue
    ];

    var stars = [];
    var nebulaParticles = [];
    var width, height, centerX, centerY;

    function rand(min, max) {
        return min + Math.random() * (max - min);
    }

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
        centerX = width * CONFIG.centerX;
        centerY = height * CONFIG.centerY;
    }

    function createStar(atEdge) {
        var angle = Math.random() * Math.PI * 2;
        var distance = atEdge
            ? rand(0.3, 0.9)
            : rand(CONFIG.spawnRadius, CONFIG.spawnRadius * 3);

        var color = COLORS[Math.floor(Math.random() * COLORS.length)];

        return {
            angle: angle,
            distance: distance,
            speed: CONFIG.baseSpeed + rand(-CONFIG.speedVariance, CONFIG.speedVariance),
            baseSpeed: CONFIG.baseSpeed,
            r: color.r,
            g: color.g,
            b: color.b,
            brightness: rand(0.6, 1.0),
            twinklePhase: Math.random() * Math.PI * 2,
            twinkleSpeed: rand(0.002, 0.006),
        };
    }

    function createNebulaParticle() {
        return {
            x: Math.random() * width,
            y: Math.random() * height,
            radius: rand(50, 150),
            alpha: rand(0.01, 0.03),
            hue: rand(200, 280),  // blue to purple range
            drift: rand(0.1, 0.3),
        };
    }

    function initStars() {
        stars = [];
        for (var i = 0; i < CONFIG.starCount; i++) {
            stars.push(createStar(true));
        }

        nebulaParticles = [];
        for (var j = 0; j < CONFIG.nebulaParticles; j++) {
            nebulaParticles.push(createNebulaParticle());
        }
    }

    function drawNebulaParticles() {
        for (var i = 0; i < nebulaParticles.length; i++) {
            var p = nebulaParticles[i];

            var gradient = ctx.createRadialGradient(
                p.x, p.y, 0,
                p.x, p.y, p.radius
            );
            gradient.addColorStop(0, "hsla(" + p.hue + ", 60%, 40%, " + p.alpha + ")");
            gradient.addColorStop(1, "transparent");

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.fillStyle = gradient;
            ctx.fill();

            // Slow drift toward edges (forward motion illusion)
            var dx = p.x - centerX;
            var dy = p.y - centerY;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist > 0) {
                p.x += (dx / dist) * p.drift;
                p.y += (dy / dist) * p.drift;
            }

            // Reset if off screen
            if (p.x < -p.radius || p.x > width + p.radius ||
                p.y < -p.radius || p.y > height + p.radius) {
                p.x = centerX + rand(-100, 100);
                p.y = centerY + rand(-100, 100);
            }
        }
    }

    function draw(time) {
        // Clear with slight fade for subtle motion blur
        ctx.fillStyle = "rgba(10, 14, 39, 0.15)";
        ctx.fillRect(0, 0, width, height);

        // Draw nebula particles (behind stars)
        drawNebulaParticles();

        // Draw and update stars
        for (var i = 0; i < stars.length; i++) {
            var s = stars[i];

            // Calculate position from polar coordinates
            var x = centerX + Math.cos(s.angle) * s.distance * width;
            var y = centerY + Math.sin(s.angle) * s.distance * height;

            // Size increases as star approaches (distance from center)
            var sizeFactor = Math.pow(s.distance, 1.5);
            var radius = CONFIG.minRadius + sizeFactor * (CONFIG.maxRadius - CONFIG.minRadius);

            // Twinkle effect
            var twinkle = 0.7 + 0.3 * Math.sin(time * s.twinkleSpeed + s.twinklePhase);
            var alpha = Math.min(1, sizeFactor * 2) * s.brightness * twinkle;

            // Color shift to blue at high speed (Doppler-like effect)
            var r = s.r;
            var g = s.g;
            var b = s.b;
            if (CONFIG.colorShift && sizeFactor < 0.3) {
                var shift = (0.3 - sizeFactor) / 0.3;
                r = Math.round(s.r * (1 - shift * 0.3));
                g = Math.round(s.g * (1 - shift * 0.1));
                b = Math.min(255, Math.round(s.b + shift * 50));
            }

            // Calculate trail (previous position)
            var prevDistance = s.distance - s.speed * CONFIG.trailLength;
            var prevX = centerX + Math.cos(s.angle) * prevDistance * width;
            var prevY = centerY + Math.sin(s.angle) * prevDistance * height;

            // Draw motion trail
            if (s.distance > 0.05 && alpha > 0.1) {
                var trailGradient = ctx.createLinearGradient(prevX, prevY, x, y);
                trailGradient.addColorStop(0, "rgba(" + r + "," + g + "," + b + ",0)");
                trailGradient.addColorStop(1, "rgba(" + r + "," + g + "," + b + "," + (alpha * 0.7).toFixed(3) + ")");

                ctx.beginPath();
                ctx.moveTo(prevX, prevY);
                ctx.lineTo(x, y);
                ctx.strokeStyle = trailGradient;
                ctx.lineWidth = Math.max(0.5, radius * 0.8);
                ctx.lineCap = "round";
                ctx.stroke();
            }

            // Draw star glow for brighter/closer stars
            if (radius > 1.2 && alpha > 0.4) {
                var glowGradient = ctx.createRadialGradient(x, y, 0, x, y, radius * 4);
                glowGradient.addColorStop(0, "rgba(" + r + "," + g + "," + b + "," + (alpha * 0.15).toFixed(3) + ")");
                glowGradient.addColorStop(1, "transparent");

                ctx.beginPath();
                ctx.arc(x, y, radius * 4, 0, Math.PI * 2);
                ctx.fillStyle = glowGradient;
                ctx.fill();
            }

            // Draw star core
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(" + r + "," + g + "," + b + "," + alpha.toFixed(3) + ")";
            ctx.fill();

            // Move star outward (forward motion)
            s.distance += s.speed * (1 + s.distance * 0.5);  // accelerate as it gets closer

            // Reset star when it goes off screen
            var maxDist = 1.2;
            if (s.distance > maxDist || x < -50 || x > width + 50 || y < -50 || y > height + 50) {
                var newStar = createStar(false);
                stars[i] = newStar;
            }
        }

        // Occasional bright flash near center (distant star burst)
        if (Math.random() < 0.002) {
            var flashX = centerX + rand(-50, 50);
            var flashY = centerY + rand(-50, 50);
            var flashGradient = ctx.createRadialGradient(flashX, flashY, 0, flashX, flashY, 30);
            flashGradient.addColorStop(0, "rgba(200, 220, 255, 0.4)");
            flashGradient.addColorStop(0.5, "rgba(100, 150, 255, 0.1)");
            flashGradient.addColorStop(1, "transparent");
            ctx.beginPath();
            ctx.arc(flashX, flashY, 30, 0, Math.PI * 2);
            ctx.fillStyle = flashGradient;
            ctx.fill();
        }

        requestAnimationFrame(draw);
    }

    window.addEventListener("resize", function () {
        resize();
        initStars();
    });

    resize();
    initStars();

    // Initial clear
    ctx.fillStyle = "rgb(10, 14, 39)";
    ctx.fillRect(0, 0, width, height);

    requestAnimationFrame(draw);
})();
