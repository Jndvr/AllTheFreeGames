// static/js/game-slideshow.js

document.addEventListener('DOMContentLoaded', function() {
    function GameSlideshow() {
        const [games, setGames] = React.useState([]);
        const [currentIndex, setCurrentIndex] = React.useState(0);
        const [isPaused, setIsPaused] = React.useState(false);
        const [fade, setFade] = React.useState(false); // New state for fade effect

        // Reference to the slideshow container for event listeners
        const slideshowRef = React.useRef(null);

        // Fisher-Yates Shuffle Algorithm to randomize the games array
        const shuffleArray = (array) => {
            let shuffled = array.slice(); // Create a copy to avoid mutating the original array
            for (let i = shuffled.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }
            return shuffled;
        };

        // Fetch game data from the provided JSON path
        React.useEffect(() => {
            console.log(`Fetching games from: ${window.GAMES_JSON_PATH}`);
            fetch(window.GAMES_JSON_PATH)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    console.log("Game data received:", data);
                    let gamesList = [];

                    // Aggregate games from all categories
                    const categories = ['prime_games', 'epic_games'];
                    categories.forEach(category => {
                        if (data[category]) {
                            data[category].forEach(game => {
                                // Optional: Add category info or any other field if needed
                                gamesList.push(game);
                            });
                        }
                    });

                    // Filter games that have both imageUrl and url
                    const filteredGames = gamesList.filter(game => game.imageUrl && game.url);
                    console.log("Filtered games before shuffling:", filteredGames);

                    // Shuffle the filteredGames array
                    const shuffledGames = shuffleArray(filteredGames);
                    console.log("Shuffled games:", shuffledGames);

                    setGames(shuffledGames);
                })
                .catch(error => {
                    console.error('Error fetching games:', error);
                });
        }, []);

        // Handle automatic slide transitions with fade effect
        React.useEffect(() => {
            if (games.length > 0 && !isPaused) {
                const interval = setInterval(() => {
                    initiateFadeTransition();
                }, 5000); // Change slide every 5 seconds

                return () => clearInterval(interval);
            }
        }, [games.length, isPaused, currentIndex]);

        // Function to initiate the fade transition
        const initiateFadeTransition = () => {
            setFade(true); // Start fade-out

            // Duration should match the CSS transition duration (1s)
            setTimeout(() => {
                setCurrentIndex(prev => (prev + 1) % games.length);
                setFade(false); // Start fade-in
            }, 1000); // 1000ms = 1s
        };

        // Handle keyboard navigation for accessibility
        React.useEffect(() => {
            const handleKeyDown = (event) => {
                if (event.key === 'ArrowRight') {
                    initiateFadeTransition();
                } else if (event.key === 'ArrowLeft') {
                    setFade(true); // Start fade-out
                    setTimeout(() => {
                        setCurrentIndex(prev => (prev - 1 + games.length) % games.length);
                        setFade(false); // Start fade-in
                    }, 1000);
                } else if (event.key === ' ') {
                    // Spacebar to toggle pause/play
                    setIsPaused(prev => !prev);
                }
            };
            window.addEventListener('keydown', handleKeyDown);
            return () => window.removeEventListener('keydown', handleKeyDown);
        }, [games.length]);

        // Function to toggle pause/play state
        const togglePause = () => {
            setIsPaused(!isPaused);
        };

        // Function to go to the next slide manually
        const goToNext = () => {
            initiateFadeTransition();
        };

        // Function to go to the previous slide manually
        const goToPrev = () => {
            setFade(true);
            setTimeout(() => {
                setCurrentIndex(prev => (prev - 1 + games.length) % games.length);
                setFade(false);
            }, 1000);
        };

        // Function to go to a specific slide (used by indicators)
        const goToSlide = (index) => {
            if (index === currentIndex) return; // No action if the same slide is clicked
            setFade(true);
            setTimeout(() => {
                setCurrentIndex(index);
                setFade(false);
            }, 1000);
        };

        if (!games.length) {
            return React.createElement(
                'div',
                {
                    className: 'w-full aspect-video bg-black rounded-lg flex items-center justify-center text-white',
                    style: { fontSize: '1.5rem' }
                },
                'Loading slideshow...'
            );
        }

        return React.createElement(
            'div',
            {
                ref: slideshowRef,
                className: 'w-full aspect-video bg-black rounded-lg overflow-hidden relative'
            },
            // Clickable Image Wrapped in an Anchor Tag with Fade Classes
            React.createElement(
                'a',
                {
                    href: games[currentIndex].url,
                    target: '_blank',
                    rel: 'noopener noreferrer',
                    className: `fade-transition ${fade ? 'opacity-0' : 'opacity-100'}`
                },
                React.createElement('img', {
                    key: `game-${currentIndex}`,
                    src: games[currentIndex].imageUrl,
                    alt: games[currentIndex].title || 'Game Image',
                    className: 'w-full h-full object-cover',
                    style: { objectPosition: 'center' },
                    loading: 'lazy', // Enables native lazy loading
                    onError: (e) => { e.target.src = '/static/images/fallback.jpg'; } // fallback if needed
                })
            ),

            // Previous Button
            React.createElement(
                'button',
                {
                    onClick: goToPrev,
                    className: 'absolute left-4 top-1/2 transform -translate-y-1/2 bg-gray-800 bg-opacity-50 text-white p-2 rounded-full hover:bg-opacity-75 focus:outline-none',
                    'aria-label': 'Previous Slide'
                },
                '<'
            ),

            // Next Button
            React.createElement(
                'button',
                {
                    onClick: goToNext,
                    className: 'absolute right-4 top-1/2 transform -translate-y-1/2 bg-gray-800 bg-opacity-50 text-white p-2 rounded-full hover:bg-opacity-75 focus:outline-none',
                    'aria-label': 'Next Slide'
                },
                '>'
            ),

            // Pause/Play Button
            React.createElement(
                'button',
                {
                    onClick: togglePause,
                    className: 'absolute bottom-4 right-4 bg-gray-800 bg-opacity-50 text-white p-2 rounded-full hover:bg-opacity-75 focus:outline-none',
                    'aria-label': isPaused ? 'Play Slideshow' : 'Pause Slideshow'
                },
                isPaused ? 'Play' : 'Pause'
            ),

            // Slide Indicators
            React.createElement(
                'div',
                {
                    className: 'absolute bottom-4 left-1/2 transform -translate-x-1/2 flex space-x-2'
                },
                games.map((game, index) =>
                    React.createElement('span', {
                        key: index,
                        className: `h-2 w-2 rounded-full cursor-pointer transition-colors duration-300 ${
                            index === currentIndex ? 'bg-white' : 'bg-gray-500 hover:bg-gray-300'
                        }`,
                        onClick: () => goToSlide(index),
                        title: game.title
                    })
                )
            )
        );
    }

    const mountNode = document.getElementById('game-slideshow');
    if (mountNode) {
        const root = ReactDOM.createRoot(mountNode);
        root.render(React.createElement(GameSlideshow));
    }
});
