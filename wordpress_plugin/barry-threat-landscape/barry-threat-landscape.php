<?php
/**
 * Plugin Name:       Barry Threat Landscape
 * Plugin URI:        https://barrycheevers.co.uk
 * Description:       Displays the daily cyber threat landscape via the [barry_threat_landscape] shortcode. Reads generated JSON produced by the Threat Landscape Pipeline.
 * Version:           1.0.0
 * Author:            Barry Cheevers
 * Author URI:        https://barrycheevers.co.uk
 * License:           GPL-2.0+
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       barry-threat-landscape
 *
 * @package BarryThreatLandscape
 */

defined( 'ABSPATH' ) || exit;

define( 'BTL_VERSION',    '1.0.0' );
define( 'BTL_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'BTL_PLUGIN_URL', plugin_dir_url( __FILE__ ) );

// ── Shortcode ────────────────────────────────────────────────────────────────

add_shortcode( 'barry_threat_landscape', 'btl_shortcode' );

/**
 * Render the [barry_threat_landscape] shortcode.
 *
 * Accepts optional attributes:
 *   title  — override page title
 *
 * @param  array|string $atts Shortcode attributes.
 * @return string             HTML output (not echoed).
 */
function btl_shortcode( $atts ) {
    $atts = shortcode_atts(
        array( 'title' => '' ),
        $atts,
        'barry_threat_landscape'
    );

    $data = btl_get_data();

    if ( is_wp_error( $data ) ) {
        return btl_render_error( $data->get_error_message() );
    }

    if ( empty( $data['threats'] ) ) {
        return btl_render_error( 'No threat data is currently available. Please check back later.' );
    }

    $title_override = sanitize_text_field( $atts['title'] );

    return btl_render_html( $data, $title_override );
}

// ── Data retrieval ───────────────────────────────────────────────────────────

/**
 * Fetch and cache the threat landscape JSON data.
 *
 * Tries the configured source (remote URL or local file path).
 * Falls back to wp-content/uploads/barry-threat-landscape/latest.json.
 *
 * @return array|WP_Error Decoded JSON as array, or WP_Error on failure.
 */
function btl_get_data() {
    $options   = get_option( 'btl_options', array() );
    $ttl       = absint( isset( $options['cache_ttl'] ) ? $options['cache_ttl'] : 3600 );
    $source    = isset( $options['json_source'] ) ? trim( $options['json_source'] ) : '';
    $cache_key = 'btl_landscape_v1';

    // Return cached data if available
    $cached = get_transient( $cache_key );
    if ( false !== $cached ) {
        return $cached;
    }

    // Determine source
    if ( filter_var( $source, FILTER_VALIDATE_URL ) ) {
        // Remote URL — only allow HTTPS to prevent plaintext credential exposure.
        $scheme = wp_parse_url( $source, PHP_URL_SCHEME );
        if ( 'https' !== strtolower( (string) $scheme ) ) {
            return new WP_Error( 'insecure_url', 'JSON source URL must use HTTPS.' );
        }
        $response = wp_remote_get( $source, array( 'timeout' => 15 ) );
        if ( is_wp_error( $response ) ) {
            return new WP_Error( 'fetch_failed', 'Could not retrieve threat data: ' . $response->get_error_message() );
        }
        $code = wp_remote_retrieve_response_code( $response );
        if ( 200 !== (int) $code ) {
            return new WP_Error( 'bad_status', "Threat data endpoint returned HTTP {$code}." );
        }
        $body = wp_remote_retrieve_body( $response );

    } elseif ( ! empty( $source ) ) {
        // Local absolute path — validate it is inside the uploads directory.
        // wp_normalize_path() ensures consistent separators on all platforms
        // (including Windows) so the strpos prefix check cannot be bypassed.
        $upload_dir  = wp_upload_dir();
        $upload_base = wp_normalize_path( $upload_dir['basedir'] );
        $real        = realpath( $source );
        if ( false === $real ) {
            return new WP_Error( 'invalid_path', 'Configured JSON path does not exist.' );
        }
        $real = wp_normalize_path( $real );
        if ( 0 !== strpos( $real, $upload_base . '/' ) ) {
            return new WP_Error( 'invalid_path', 'Configured JSON path must be within the uploads directory.' );
        }
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
        $body = file_get_contents( $real );
        if ( false === $body ) {
            return new WP_Error( 'read_failed', 'Could not read the local JSON file.' );
        }

    } else {
        // Default upload location
        $default = wp_upload_dir()['basedir'] . '/barry-threat-landscape/latest.json';
        if ( ! file_exists( $default ) ) {
            return new WP_Error( 'not_found', 'Threat landscape data file not found at ' . esc_html( $default ) . '.' );
        }
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
        $body = file_get_contents( $default );
    }

    $data = json_decode( $body, true );
    if ( ! is_array( $data ) ) {
        return new WP_Error( 'invalid_json', 'The threat landscape data could not be parsed.' );
    }

    set_transient( $cache_key, $data, max( 60, $ttl ) );

    return $data;
}

// ── Rendering ────────────────────────────────────────────────────────────────

/**
 * Render the full threat landscape HTML.
 *
 * Everything here is output through esc_html / esc_url / wp_kses — no raw
 * user-controlled data is ever echoed directly.
 *
 * @param  array  $data           Decoded JSON array.
 * @param  string $title_override Optional title to display.
 * @return string HTML string.
 */
function btl_render_html( array $data, string $title_override = '' ): string {
    $options    = get_option( 'btl_options', array() );
    $page_title = $title_override ?: ( isset( $options['title_override'] ) ? sanitize_text_field( $options['title_override'] ) : 'Cyber Threat Landscape Today' );

    $generated_at = isset( $data['generated_at'] ) ? sanitize_text_field( $data['generated_at'] ) : '';
    $threats      = isset( $data['threats'] ) && is_array( $data['threats'] ) ? $data['threats'] : array();

    ob_start();
    ?>
    <div class="btl-wrap" id="btl-landscape">
      <div class="btl-header">
        <h2 class="btl-title"><?php echo esc_html( $page_title ); ?></h2>
        <?php if ( $generated_at ) : ?>
        <p class="btl-updated">Last updated: <?php echo esc_html( $generated_at ); ?></p>
        <?php endif; ?>
        <p class="btl-count"><?php echo esc_html( count( $threats ) ); ?> threat<?php echo count( $threats ) !== 1 ? 's' : ''; ?> in today&rsquo;s briefing</p>
      </div>

      <?php if ( empty( $threats ) ) : ?>
      <p class="btl-empty">No threat data is currently available.</p>
      <?php else : ?>

      <ol class="btl-list">
        <?php foreach ( $threats as $i => $threat ) :
            if ( ! is_array( $threat ) ) continue;
            $rank   = $i + 1;
            $title  = isset( $threat['title'] ) ? sanitize_text_field( $threat['title'] ) : 'Unknown';
            $url    = isset( $threat['primary_url'] ) ? esc_url( $threat['primary_url'] ) : '#';
            $source = isset( $threat['primary_source'] ) ? sanitize_text_field( $threat['primary_source'] ) : '';
            $pub    = isset( $threat['published_at'] ) ? sanitize_text_field( $threat['published_at'] ) : '';
            $summary    = isset( $threat['summary'] ) ? sanitize_text_field( $threat['summary'] ) : '';
            $why        = isset( $threat['why_it_matters'] ) ? sanitize_text_field( $threat['why_it_matters'] ) : '';
            $cves       = isset( $threat['cves'] ) && is_array( $threat['cves'] ) ? $threat['cves'] : array();
            $malware    = isset( $threat['malware_families'] ) && is_array( $threat['malware_families'] ) ? $threat['malware_families'] : array();
            $techniques = isset( $threat['attack_techniques'] ) && is_array( $threat['attack_techniques'] ) ? $threat['attack_techniques'] : array();
            $countries  = isset( $threat['countries_affected'] ) && is_array( $threat['countries_affected'] ) ? $threat['countries_affected'] : array();
            $sectors    = isset( $threat['industries_affected'] ) && is_array( $threat['industries_affected'] ) ? $threat['industries_affected'] : array();
            $conf_note  = isset( $threat['confidence_note'] ) ? sanitize_text_field( $threat['confidence_note'] ) : '';
            $stix_file  = isset( $threat['stix_file'] ) ? sanitize_text_field( $threat['stix_file'] ) : '';
            $corroboration = isset( $threat['corroboration_count'] ) ? absint( $threat['corroboration_count'] ) : 1;
        ?>
        <li class="btl-card" id="btl-threat-<?php echo esc_attr( $rank ); ?>">
          <div class="btl-card-header">
            <span class="btl-rank" aria-label="Rank <?php echo esc_attr( $rank ); ?>"><?php echo esc_html( $rank ); ?></span>
            <div class="btl-card-title-wrap">
              <h3 class="btl-card-title">
                <a href="<?php echo $url; ?>" target="_blank" rel="noopener noreferrer"><?php echo esc_html( $title ); ?></a>
              </h3>
              <div class="btl-card-meta">
                <span class="btl-source-badge"><?php echo esc_html( $source ); ?></span>
                <?php if ( $pub ) : ?><span class="btl-pub-date"><?php echo esc_html( $pub ); ?></span><?php endif; ?>
                <?php if ( $corroboration > 1 ) : ?>
                <span class="btl-corroboration"><?php echo esc_html( $corroboration ); ?> sources</span>
                <?php endif; ?>
              </div>
            </div>
          </div>

          <?php if ( $summary ) : ?>
          <div class="btl-summary">
            <p><?php echo esc_html( $summary ); ?></p>
          </div>
          <?php endif; ?>

          <!-- Badges -->
          <div class="btl-badges">
            <?php foreach ( $techniques as $tech ) :
                if ( ! is_array( $tech ) ) continue;
                $tid  = isset( $tech['id'] ) ? sanitize_text_field( $tech['id'] ) : '';
                $tname = isset( $tech['name'] ) ? sanitize_text_field( $tech['name'] ) : '';
                if ( ! $tid ) continue;
            ?>
            <a href="<?php echo esc_url( "https://attack.mitre.org/techniques/{$tid}/" ); ?>"
               target="_blank" rel="noopener noreferrer" class="btl-badge btl-badge--attack">
                <?php echo esc_html( "{$tid}: {$tname}" ); ?>
            </a>
            <?php endforeach; ?>

            <?php foreach ( $cves as $cve ) :
                $cve_safe = sanitize_text_field( $cve );
            ?>
            <a href="<?php echo esc_url( "https://nvd.nist.gov/vuln/detail/{$cve_safe}" ); ?>"
               target="_blank" rel="noopener noreferrer" class="btl-badge btl-badge--cve">
                <?php echo esc_html( $cve_safe ); ?>
            </a>
            <?php endforeach; ?>

            <?php foreach ( $malware as $mal ) : ?>
            <span class="btl-badge btl-badge--malware"><?php echo esc_html( sanitize_text_field( $mal ) ); ?></span>
            <?php endforeach; ?>

            <?php foreach ( $sectors as $sec ) :
                if ( 'Unknown' === $sec ) continue;
            ?>
            <span class="btl-badge btl-badge--sector"><?php echo esc_html( sanitize_text_field( $sec ) ); ?></span>
            <?php endforeach; ?>

            <?php foreach ( $countries as $country ) :
                if ( 'Unknown' === $country ) continue;
            ?>
            <span class="btl-badge btl-badge--country"><?php echo esc_html( sanitize_text_field( $country ) ); ?></span>
            <?php endforeach; ?>
          </div>

          <!-- Why it matters -->
          <?php if ( $why ) : ?>
          <div class="btl-why">
            <strong>Why it matters:</strong> <?php echo esc_html( $why ); ?>
          </div>
          <?php endif; ?>

          <!-- STIX download link -->
          <?php if ( $stix_file ) :
              $base_url = isset( $options['json_source'] )
                  ? trailingslashit( dirname( $options['json_source'] ) )
                  : trailingslashit( wp_upload_dir()['baseurl'] ) . 'barry-threat-landscape/';
              $stix_url = $base_url . ltrim( $stix_file, '/' );
          ?>
          <div class="btl-stix-link">
            <a href="<?php echo esc_url( $stix_url ); ?>" download class="btl-btn">
              Download STIX 2.1
            </a>
          </div>
          <?php endif; ?>

          <!-- Confidence note -->
          <?php if ( $conf_note ) : ?>
          <p class="btl-confidence-note"><?php echo esc_html( $conf_note ); ?></p>
          <?php endif; ?>

        </li>
        <?php endforeach; ?>
      </ol>

      <div class="btl-disclaimer">
        <p><strong>Disclaimer:</strong> ATT&amp;CK technique mappings, attribution, and affected sector/country fields are best-effort analytical outputs based on keyword analysis of public sources. They may be incomplete or incorrect. Always consult the original source and qualified security professionals before taking action.</p>
      </div>

      <?php endif; ?>
    </div>
    <?php
    return ob_get_clean();
}

/**
 * Render a graceful error message.
 *
 * @param  string $message Error message.
 * @return string HTML string.
 */
function btl_render_error( string $message ): string {
    return '<div class="btl-error"><p><strong>Threat Landscape:</strong> ' . esc_html( $message ) . '</p></div>';
}

// ── Plugin styles ─────────────────────────────────────────────────────────────

add_action( 'wp_enqueue_scripts', 'btl_enqueue_styles' );

/**
 * Enqueue the plugin stylesheet.
 */
function btl_enqueue_styles(): void {
    wp_enqueue_style(
        'barry-threat-landscape',
        BTL_PLUGIN_URL . 'btl-style.css',
        array(),
        BTL_VERSION
    );
}

// ── Admin settings ────────────────────────────────────────────────────────────

add_action( 'admin_menu', 'btl_admin_menu' );
add_action( 'admin_init', 'btl_register_settings' );

/**
 * Register the settings page under Settings > Threat Landscape.
 */
function btl_admin_menu(): void {
    add_options_page(
        'Threat Landscape Settings',
        'Threat Landscape',
        'manage_options',
        'barry-threat-landscape',
        'btl_settings_page'
    );
}

/**
 * Register plugin settings.
 */
function btl_register_settings(): void {
    register_setting( 'btl_options_group', 'btl_options', 'btl_sanitise_options' );

    add_settings_section(
        'btl_main_section',
        'Data Source',
        null,
        'barry-threat-landscape'
    );

    add_settings_field(
        'json_source',
        'JSON Source URL or Path',
        'btl_field_json_source',
        'barry-threat-landscape',
        'btl_main_section'
    );

    add_settings_field(
        'cache_ttl',
        'Cache TTL (seconds)',
        'btl_field_cache_ttl',
        'barry-threat-landscape',
        'btl_main_section'
    );

    add_settings_field(
        'title_override',
        'Page Title Override',
        'btl_field_title_override',
        'barry-threat-landscape',
        'btl_main_section'
    );
}

/**
 * Sanitise plugin options before saving.
 *
 * @param  mixed $input Raw input.
 * @return array        Sanitised options.
 */
function btl_sanitise_options( $input ): array {
    $clean = array();

    if ( isset( $input['json_source'] ) ) {
        $src = trim( $input['json_source'] );
        if ( filter_var( $src, FILTER_VALIDATE_URL ) ) {
            // Only allow HTTPS URLs to prevent plaintext data transfer.
            $scheme = wp_parse_url( $src, PHP_URL_SCHEME );
            if ( 'https' === strtolower( (string) $scheme ) ) {
                $clean['json_source'] = esc_url_raw( $src );
            } else {
                add_settings_error( 'btl_options', 'insecure_url', 'JSON source URL must use HTTPS.', 'error' );
                $clean['json_source'] = '';
            }
        } else {
            // Treat as local file path (validated on use)
            $clean['json_source'] = sanitize_text_field( $src );
        }
    }

    $clean['cache_ttl'] = isset( $input['cache_ttl'] )
        ? max( 60, absint( $input['cache_ttl'] ) )
        : 3600;

    $clean['title_override'] = isset( $input['title_override'] )
        ? sanitize_text_field( $input['title_override'] )
        : '';

    // Invalidate cached data when settings change
    delete_transient( 'btl_landscape_v1' );

    return $clean;
}

/**
 * Settings page HTML.
 */
function btl_settings_page(): void {
    if ( ! current_user_can( 'manage_options' ) ) {
        wp_die( esc_html__( 'You do not have sufficient permissions to access this page.' ) );
    }
    ?>
    <div class="wrap">
      <h1><?php esc_html_e( 'Threat Landscape Settings', 'barry-threat-landscape' ); ?></h1>
      <form method="post" action="options.php">
        <?php
        settings_fields( 'btl_options_group' );
        do_settings_sections( 'barry-threat-landscape' );
        submit_button();
        ?>
      </form>
      <hr>
      <h2><?php esc_html_e( 'Usage', 'barry-threat-landscape' ); ?></h2>
      <p><?php esc_html_e( 'Add the following shortcode to any page or post:', 'barry-threat-landscape' ); ?></p>
      <code>[barry_threat_landscape]</code>
      <p><?php esc_html_e( 'Optional attributes:', 'barry-threat-landscape' ); ?></p>
      <code>[barry_threat_landscape title="Today's Top Threats"]</code>
      <hr>
      <h2><?php esc_html_e( 'Cache', 'barry-threat-landscape' ); ?></h2>
      <form method="post">
        <?php wp_nonce_field( 'btl_flush_cache', 'btl_nonce' ); ?>
        <input type="hidden" name="btl_action" value="flush_cache">
        <?php submit_button( 'Flush Cache Now', 'secondary' ); ?>
      </form>
    </div>
    <?php
}

// Handle cache flush from settings page
add_action( 'admin_init', function () {
    if (
        isset( $_POST['btl_action'] )
        && 'flush_cache' === $_POST['btl_action']
        && isset( $_POST['btl_nonce'] )
        && wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['btl_nonce'] ) ), 'btl_flush_cache' )
        && current_user_can( 'manage_options' )
    ) {
        delete_transient( 'btl_landscape_v1' );
        add_action( 'admin_notices', function () {
            echo '<div class="notice notice-success is-dismissible"><p>Threat Landscape cache flushed.</p></div>';
        } );
    }
} );

/** Settings field: JSON source */
function btl_field_json_source(): void {
    $opts = get_option( 'btl_options', array() );
    $val  = isset( $opts['json_source'] ) ? $opts['json_source'] : '';
    ?>
    <input type="text" name="btl_options[json_source]"
           value="<?php echo esc_attr( $val ); ?>"
           class="regular-text"
           placeholder="https://example.com/path/latest.json">
    <p class="description">
        Remote URL (<code>https://…</code>) or absolute server path to <code>latest.json</code>.<br>
        Leave blank to use the default: <code>/wp-content/uploads/barry-threat-landscape/latest.json</code>.
    </p>
    <?php
}

/** Settings field: cache TTL */
function btl_field_cache_ttl(): void {
    $opts = get_option( 'btl_options', array() );
    $val  = isset( $opts['cache_ttl'] ) ? absint( $opts['cache_ttl'] ) : 3600;
    ?>
    <input type="number" name="btl_options[cache_ttl]"
           value="<?php echo esc_attr( $val ); ?>"
           min="60" step="60" class="small-text">
    <p class="description">How long (in seconds) to cache the fetched data. Minimum 60. Default: 3600 (1 hour).</p>
    <?php
}

/** Settings field: title override */
function btl_field_title_override(): void {
    $opts = get_option( 'btl_options', array() );
    $val  = isset( $opts['title_override'] ) ? $opts['title_override'] : '';
    ?>
    <input type="text" name="btl_options[title_override]"
           value="<?php echo esc_attr( $val ); ?>"
           class="regular-text"
           placeholder="Cyber Threat Landscape Today">
    <p class="description">Override the default page heading. Leave blank to use the default.</p>
    <?php
}

// ── Uninstall hook ────────────────────────────────────────────────────────────

register_uninstall_hook( __FILE__, 'btl_uninstall' );

/**
 * Clean up on plugin deletion.
 */
function btl_uninstall(): void {
    delete_option( 'btl_options' );
    delete_transient( 'btl_landscape_v1' );
}
