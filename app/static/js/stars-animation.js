/**
 * Canvas-based animated starfield with depth layers and shooting stars.
 */
(function () {
    "use strict";

    var canvas = document.getElementById("starfield");
    if (!canvas) return;

    var ctx = canvas.getContext("2d");

    // Depth layers: far (dim, slow), mid, near (bright, faster)
    var layers = [
        { count: 120, minR: 0.2, maxR: 0.6, minA: 0.15, maxA: 0.4, drift: 0.02, twinkle: 0.008 },
        { count: 80,  minR: 0.4, maxR: 1.0, minA: 0.3,  maxA: 0.6, drift: 0.05, twinkle: 0.015 },
        { count: 40,  minR: 0.8, maxR: 1.8, minA: 0.5,  maxA: 0.9, drift: 0.08, twinkle: 0.025 },
    ];

    // Color tints for variety
    var tints = [
        [255, 255, 255],   // white
        [200, 220, 255],   // cool blue
        [255, 240, 220],   // warm
        [180, 200, 255],   // steel blue
        [220, 200, 255],   // lavender
    ];

    var stars = [];
    var shootingStars = [];
    var SHOOTING_INTERVAL = 4000; // ms between shooting stars
    var lastShootingTime = 0;

    function rand(min, max) {
        return min + Math.random() * (max - min);
    }

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }

    function createStars() {
        stars = [];
        for (var li = 0; li < layers.length; li++) {
            var L = layers[li];
            for (var i = 0; i < L.count; i++) {
                var tint = tints[Math.floor(Math.random() * tints.length)];
                stars.push({
                    x: Math.random() * canvas.width,
                    y: Math.random() * canvas.height,
                    radius: rand(L.minR, L.maxR),
                    alpha: rand(L.minA, L.maxA),
                    twinkleSpeed: rand(L.twinkle * 0.5, L.twinkle * 1.5),
                    twinklePhase: Math.random() * Math.PI * 2,
                    drift: (Math.random() - 0.5) * L.drift,
                    r: tint[0],
                    g: tint[1],
                    b: tint[2],
                    layer: li,
                });
            }
        }
    }

    function spawnShootingStar() {
        var startX = rand(canvas.width * 0.1, canvas.width * 0.9);
        var startY = rand(0, canvas.height * 0.4);
        var angle = rand(0.3, 0.8); // radians, mostly diagonal
        var speed = rand(6, 12);

        shootingStars.push({
            x: startX,
            y: startY,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            life: 1.0,
            decay: rand(0.012, 0.025),
            length: rand(40, 80),
        });
    }

    function draw(time) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw stars
        for (var i = 0; i < stars.length; i++) {
            var s = stars[i];
            var twinkle = 0.5 + 0.5 * Math.sin(time * s.twinkleSpeed + s.twinklePhase);
            var alpha = s.alpha * twinkle;

            // Glow for brighter stars
            if (s.radius > 1.0 && alpha > 0.5) {
                ctx.beginPath();
                ctx.arc(s.x, s.y, s.radius * 3, 0, Math.PI * 2);
                ctx.fillStyle = "rgba(" + s.r + "," + s.g + "," + s.b + "," + (alpha * 0.08).toFixed(3) + ")";
                ctx.fill();
            }

            ctx.beginPath();
            ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(" + s.r + "," + s.g + "," + s.b + "," + alpha.toFixed(3) + ")";
            ctx.fill();

            // Drift
            s.y += s.drift;
            if (s.y < -2) s.y = canvas.height + 2;
            if (s.y > canvas.height + 2) s.y = -2;
        }

        // Shooting stars
        if (time - lastShootingTime > SHOOTING_INTERVAL && Math.random() < 0.3) {
            spawnShootingStar();
            lastShootingTime = time;
        }

        for (var j = shootingStars.length - 1; j >= 0; j--) {
            var ss = shootingStars[j];

            ctx.beginPath();
            ctx.moveTo(ss.x, ss.y);
            ctx.lineTo(ss.x - ss.vx * (ss.length / 10), ss.y - ss.vy * (ss.length / 10));

            var grad = ctx.createLinearGradient(
                ss.x, ss.y,
                ss.x - ss.vx * (ss.length / 10),
                ss.y - ss.vy * (ss.length / 10)
            );
            grad.addColorStop(0, "rgba(255, 255, 255, " + (ss.life * 0.9).toFixed(3) + ")");
            grad.addColorStop(1, "rgba(255, 255, 255, 0)");

            ctx.strokeStyle = grad;
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Bright head
            ctx.beginPath();
            ctx.arc(ss.x, ss.y, 1.5, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(255, 255, 255, " + ss.life.toFixed(3) + ")";
            ctx.fill();

            ss.x += ss.vx;
            ss.y += ss.vy;
            ss.life -= ss.decay;

            if (ss.life <= 0 || ss.x > canvas.width + 20 || ss.y > canvas.height + 20) {
                shootingStars.splice(j, 1);
            }
        }

        requestAnimationFrame(draw);
    }

    window.addEventListener("resize", function () {
        resize();
        createStars();
    });

    resize();
    createStars();
    requestAnimationFrame(draw);
})();