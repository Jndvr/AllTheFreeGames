// static/js/game-slideshow.js

document.addEventListener('DOMContentLoaded', function() {
    function GameSlideshow() {
        const [games, setGames] = React.useState([]);
        const [currentIndex, setCurrentIndex] = React.useState(0);

        // Fisher-Yates Shuffle Algorithm
        const shuffleArray = (array) => {
            let shuffled = array.slice(); // Create a copy to avoid mutating the original array
            for (let i = shuffled.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }
            return shuffled;
        };

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

                    // Aggregate games from desired categories
                    if (data.prime_games) {
                        data.prime_games.forEach(game => {
                            game.platform = 'Prime Free Games';
                            gamesList.push(game);
                        });
                    }

                    if (data.epic_games) {
                        data.epic_games.forEach(game => {
                            game.platform = 'Epic Free Games';
                            gamesList.push(game);
                        });
                    }

                    // Uncomment the following if you wish to include more platforms in the slideshow:
                    /*
                    if (data.steam_games) {
                        data.steam_games.forEach(game => {
                            game.platform = 'Steam Free Games';
                            gamesList.push(game);
                        });
                    }
                    if (data.gog_free) {
                        data.gog_free.forEach(game => {
                            game.platform = 'GOG Free Games';
                            gamesList.push(game);
                        });
                    }
                    */

                    // Filter games that have an imageUrl
                    const filteredGames = gamesList.filter(game => game.imageUrl);
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

        React.useEffect(() => {
            if (games.length > 0) {
                const interval = setInterval(() => {
                    setCurrentIndex(prev => (prev + 1) % games.length);
                }, 5000); // Change slide every 5 seconds
                return () => clearInterval(interval);
            }
        }, [games.length]);

        if (!games.length) {
            return React.createElement('div', {
                className: 'w-full aspect-video bg-black rounded-lg'
            });
        }

        return React.createElement('div', {
            className: 'w-full aspect-video bg-black rounded-lg overflow-hidden relative'
        }, 
            React.createElement('div', {
                className: 'absolute inset-0 flex items-center justify-center'
            },
                React.createElement('img', {
                    key: `game-${currentIndex}`,
                    src: games[currentIndex].imageUrl,
                    alt: games[currentIndex].title,
                    className: 'w-full h-full object-cover',
                    style: {
                        objectPosition: 'center'
                    }
                })
            )
        );
    }

    const mountNode = document.getElementById('game-slideshow');
    if (mountNode) {
        const root = ReactDOM.createRoot(mountNode);
        root.render(React.createElement(GameSlideshow));
    }
});
